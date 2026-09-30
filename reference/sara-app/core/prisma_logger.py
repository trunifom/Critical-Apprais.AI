"""
PRISMALogger
------------
Append-only audit logger tailored to PRISMA 2020 reporting for systematic reviews.

Core responsibilities:
- Record process steps as structured, immutable events with stable schemas.
- Maintain a live, in-memory rollup with PRISMA-relevant aggregates.
- Export logs to JSON/CSV for download and optionally persist them to Supabase.
- Support both single-source and multi-source workflows.

Design principles:
- Transparency: we log what was identified, merged, marked as duplicates, validated, screened, and exported.
- Non-destructive pipelines: duplicates and missing abstracts may be "conceptually removed" for counting,
  but rows can remain in data tables (they are merely marked). The logger remains agnostic to physical deletion.
- Backward-compatible API: methods continue to work if you pass traditional "before/after" sizes,
  but also accept explicit "duplicates_marked" counts to support mark-only pipelines.

Note on "removed" vs "marked":
- PRISMA reporting uses "duplicates removed" semantics. In mark-only pipelines, we conceptually treat
  "duplicates marked" as "duplicates removed before screening" for reporting (even if rows remain in the dataset),
  to ensure counts align with PRISMA flow expectations.
"""

from __future__ import annotations

import csv
import json
import logging
import uuid
from typing import Any, Dict, List, Optional
from datetime import datetime

from core.enums import (
    PrismaStep, EventType, LogLevel, ScreeningPhase, RunStatus,
    DuplicatesReportingMode,
)

LOG = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    """Return an ISO 8601 UTC timestamp with trailing 'Z'."""
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


class PRISMALogger:
    """
    Append-only audit logger for PRISMA 2020.

    Responsibilities:
    - Record steps as structured events with stable payloads.
    - Maintain a live rollup for instantaneous PRISMA flow derivation.
    - Export logs and optionally persist to Supabase (if a client is injected).

    Highlights:
    - Per-source dedup is logged with explicit source_id/label.
    - Merge is logged once with a full list of inputs.
    - Global dedup (across sources) is logged once and used for BETWEEN_DATABASES_ONLY mode.
    - Screening is logged as aggregates; no per-study logging here.
    - Support for mark-only dedup and for marking missing abstracts prior to screening.
    """

    # --------------------------- init & header ---------------------------------

    def __init__(
        self,
        project_id: str,
        project_title: str,
        user_id: Optional[str] = None,
        supabase_client: Optional[Any] = None,
        duplicates_reporting_mode: DuplicatesReportingMode = DuplicatesReportingMode.ALL_BEFORE_SCREENING,
    ) -> None:
        """
        :param project_id: Stable UUID for the project.
        :param project_title: Human-readable project title.
        :param user_id: Optional user identifier (Supabase auth user id).
        :param supabase_client: Optional Supabase client for persistence (table writes).
        :param duplicates_reporting_mode: Controls PRISMA 'duplicates removed' calculation.
        """
        self.project_id = project_id
        self.project_title = project_title
        self.user_id = user_id
        self.supabase = supabase_client
        self.duplicates_reporting_mode = duplicates_reporting_mode

        self.run_id: Optional[str] = None

        # Header captures run context for reproducibility (no study-level PII).
        self.header: Dict[str, Any] = {
            "project_id": project_id,
            "project_title": project_title,
            "created_at": _utc_now_iso(),
            "user_id": user_id,
            "framework": None,            # e.g., "PICOS"
            "criteria": None,             # structured dict/string snapshot
            "objectives": [],
            "mode": None,                 # "abstract" | "fulltext"
            "llm": None,                  # dict: provider, model name/version, prompt id, params
            "run_started_at": None,
            "run_ended_at": None,
            "duplicates_reporting_mode": str(duplicates_reporting_mode),
        }

        # Append-only in-memory event list
        self.events: List[Dict[str, Any]] = []

        # Live rollup used to derive PRISMA flow numbers quickly in the UI.
        # We separate within-source vs global dedup to support both reporting modes.
        self.rollup: Dict[str, Any] = {
            # Identification
            "identified_total": 0,                 # Sum of all SOURCE_IMPORTED.records_identified
            "identified_by_source": {},            # label -> count

            # Per-source dedup (conceptual removals; rows may actually be marked)
            "within_source_removed_by_label": {},  # label -> count
            "within_source_removed_total": 0,

            # Merge & global dedup (conceptual removals across sources)
            "merged_before_global_dedup": None,    # int or None; sum of inputs
            "dedup_global": {                      # last global dedup snapshot
                "before": None, "after": None, "removed": 0
            },

            # Pre-screening validation (e.g., missing abstracts)
            "missing_abstracts_total": 0,          # total records marked as missing abstracts

            # Screening aggregates
            "abstract_screen": {
                "included": 0, "excluded": 0, "conflicts": 0, "reasons": {}
            },
            "fulltext_screen": {
                "included": 0, "excluded": 0, "conflicts": 0, "reasons": {}
            },

            # Final
            "final_included": None,  # may be computed or set at end_run()
        }

    # --------------------------- configuration --------------------------------

    def set_duplicates_reporting_mode(self, mode: DuplicatesReportingMode) -> None:
        """Update the duplicates reporting mode for subsequent flow calculations."""
        self.duplicates_reporting_mode = mode
        self.header["duplicates_reporting_mode"] = str(mode)

    # --------------------------- run lifecycle ---------------------------------

    def start_run(
        self,
        framework: str,
        criteria: Dict[str, Any],
        objectives: List[str],
        mode: str,
        llm_info: Dict[str, Any],
    ) -> str:
        """
        Open a new run. All subsequent events will be tied to this run_id.
        """
        self.run_id = str(uuid.uuid4())
        self.header.update({
            "framework": framework,
            "criteria": criteria,
            "objectives": objectives,
            "mode": mode,
            "llm": llm_info,
            "run_started_at": _utc_now_iso(),
        })
        self._write_run_row_to_supabase(status=RunStatus.RUNNING.value)
        return self.run_id

    def end_run(self, status: str = RunStatus.COMPLETED.value, message: Optional[str] = None) -> None:
        """
        Close the run and upsert a final summary to the DB (if configured).
        """
        self.header["run_ended_at"] = _utc_now_iso()
        # Optionally compute 'final_included' if not set explicitly:
        if self.rollup["final_included"] is None:
            # If fulltext screening happened, prefer that; else use abstract.
            ft = self.rollup["fulltext_screen"]
            ab = self.rollup["abstract_screen"]
            final = ft["included"] if (ft["included"] + ft["excluded"]) > 0 else ab["included"]
            self.rollup["final_included"] = final

        self._write_run_row_to_supabase(status=status, message=message)

    # --------------------------- event logging ---------------------------------

    def log_source_imported(
        self,
        source_id: str,
        source_label: str,
        original_filename: str,
        file_type: str,
        records_identified: int,
        message: Optional[str] = None,
    ) -> None:
        """
        Record a single source import (pre-dedup, pre-merge).
        """
        msg = message or f"Imported source '{source_label}' with {records_identified} records."
        payload = {
            "source_id": source_id,
            "source_label": source_label,
            "original_filename": original_filename,
            "file_type": file_type,
            "records_identified": int(records_identified),
        }
        self._append_event(
            step=PrismaStep.IMPORT,
            event_type=EventType.SOURCE_IMPORTED,
            level=LogLevel.INFO,
            message=msg,
            payload=payload,
            source_id=source_id,
        )
        # rollup
        self.rollup["identified_total"] += int(records_identified)
        by_src = self.rollup["identified_by_source"]
        by_src[source_label] = by_src.get(source_label, 0) + int(records_identified)

    def log_dedup_within_source(
        self,
        source_id: str,
        source_label: str,
        before: int,
        after: int,
        method: str,
        message: Optional[str] = None,
        duplicates_marked: Optional[int] = None,
    ) -> None:
        """
        Record an optional per-source duplicate handling step.

        For mark-only pipelines (no physical row removal), pass 'duplicates_marked'
        with the count of duplicates you marked in the dataset. In that case,
        we still populate 'removed' in the payload/rollup to maintain PRISMA semantics.

        For destructive pipelines, you can omit 'duplicates_marked' and rely on
        (before - after) to compute removals.
        """
        # Compute the conceptual 'removed' number
        if duplicates_marked is not None:
            removed = max(0, int(duplicates_marked))
        else:
            removed = max(0, int(before) - int(after))

        msg = message or f"Per-source duplicate handling on '{source_label}': removed {removed} (method={method})."
        payload = {
            "source_id": source_id,
            "source_label": source_label,
            "before": int(before),
            "after": int(after),
            "removed": int(removed),
            "method": method,
            "scope": "within_source",
        }
        if duplicates_marked is not None:
            payload["marked"] = int(duplicates_marked)

        self._append_event(
            step=PrismaStep.DEDUP_PER_SOURCE,
            event_type=EventType.DEDUP_WITHIN_SOURCE,
            level=LogLevel.INFO,
            message=msg,
            payload=payload,
            source_id=source_id,
        )
        # rollup
        by_label = self.rollup["within_source_removed_by_label"]
        by_label[source_label] = by_label.get(source_label, 0) + int(removed)
        self.rollup["within_source_removed_total"] += int(removed)

    def log_merge_all_sources(
        self,
        inputs: List[Dict[str, Any]],
        merged_records_before_global_dedup: int,
        message: Optional[str] = None,
    ) -> None:
        """
        Record a single merge event consolidating all sources.
        'inputs' should list each source with counts AFTER any within-source dedup.
        """
        msg = message or "Merged all sources into a single dataset."
        payload = {
            "inputs": inputs,  # e.g. [{"source_id": "...", "source_label": "...", "records_after_within_source_dedup": 1020}, ...]
            "merged_records_before_global_dedup": int(merged_records_before_global_dedup),
        }
        self._append_event(
            step=PrismaStep.MERGE,
            event_type=EventType.MERGE_ALL_SOURCES,
            level=LogLevel.INFO,
            message=msg,
            payload=payload,
        )
        self.rollup["merged_before_global_dedup"] = int(merged_records_before_global_dedup)

    def log_dedup_global(
        self,
        before: int,
        after: int,
        method: str,
        message: Optional[str] = None,
        duplicates_marked: Optional[int] = None,
    ) -> None:
        """
        Record the single, canonical cross-source duplicate handling step.

        For mark-only pipelines, pass 'duplicates_marked' with the count of duplicates
        that would be considered 'removed before screening' for PRISMA purposes.
        """
        if duplicates_marked is not None:
            removed = max(0, int(duplicates_marked))
        else:
            removed = max(0, int(before) - int(after))

        msg = message or f"Global duplicate handling (across sources): removed {removed} (method={method})."
        payload = {
            "before": int(before),
            "after": int(after),
            "removed": int(removed),
            "method": method,
            "scope": "across_sources",
        }
        if duplicates_marked is not None:
            payload["marked"] = int(duplicates_marked)

        self._append_event(
            step=PrismaStep.DEDUP_MERGED,
            event_type=EventType.DEDUP_GLOBAL,
            level=LogLevel.INFO,
            message=msg,
            payload=payload,
        )
        self.rollup["dedup_global"] = {"before": int(before), "after": int(after), "removed": int(removed)}

    # ---- Pre-screening validation (e.g., missing abstracts) -------------------

    def log_missing_abstracts_marked(
        self,
        scope: str,
        total_count: int,
        missing_count: int,
        message: Optional[str] = None,
        source_id: Optional[str] = None,
        source_label: Optional[str] = None,
    ) -> None:
        """
        Record that a validation step marked records with missing abstracts.

        :param scope: "within_source" or "across_sources"
        :param total_count: Total records considered in this validation step
        :param missing_count: Number of records marked as missing abstracts
        :param message: Optional message (defaults to a concise summary)
        :param source_id: Optional source id if scope == "within_source"
        :param source_label: Optional source label if scope == "within_source"
        """
        msg = message or f"Missing abstracts marked ({scope}): {int(missing_count)} of {int(total_count)}."
        payload: Dict[str, Any] = {
            "scope": scope,
            "total_count": int(total_count),
            "missing_count": int(missing_count),
            "missing_percentage": round((int(missing_count) / int(total_count) * 100), 2) if int(total_count) > 0 else 0.0,
        }
        if source_id:
            payload["source_id"] = source_id
        if source_label:
            payload["source_label"] = source_label

        # We reuse WARNING as an informational event type for validations.
        self._append_event(
            step=(PrismaStep.DEDUP_PER_SOURCE if scope == "within_source" else PrismaStep.DEDUP_MERGED),
            event_type=EventType.WARNING,
            level=LogLevel.INFO,
            message=msg,
            payload=payload,
            source_id=source_id,
        )

        # Update rollup (accumulate across calls)
        self.rollup["missing_abstracts_total"] += int(missing_count)

    # --------------------------- screening -------------------------------------

    def log_screening(
        self,
        phase: ScreeningPhase,
        included: int,
        excluded: int,
        conflicts: int = 0,
        reasons: Optional[Dict[str, int]] = None,
        model_snapshot: Optional[Dict[str, Any]] = None,
        message: Optional[str] = None,
    ) -> None:
        """
        Log aggregated screening results for either Title/Abstract or Full-Text phase.
        """
        reasons = reasons or {}
        bucket = "abstract_screen" if phase == ScreeningPhase.ABSTRACT else "fulltext_screen"
        plural = "Title/Abstract" if phase == ScreeningPhase.ABSTRACT else "Full-text"
        msg = message or (f"{plural} screening: included={included}, excluded={excluded}, "
                          f"conflicts={conflicts}, reasons={sum(reasons.values())} (codes).")
        payload = {
            "included": int(included),
            "excluded": int(excluded),
            "conflicts": int(conflicts),
            "reasons": reasons if phase == ScreeningPhase.ABSTRACT else None,
            "reasons_fulltext": reasons if phase == ScreeningPhase.FULLTEXT else None,
            "model_snapshot": model_snapshot or {},
        }
        self._append_event(
            step=(PrismaStep.SCREEN_ABSTRACT if phase == ScreeningPhase.ABSTRACT else PrismaStep.SCREEN_FULLTEXT),
            event_type=(EventType.SCREEN_TA if phase == ScreeningPhase.ABSTRACT else EventType.SCREEN_FT),
            level=LogLevel.INFO,
            message=msg,
            payload=payload,
        )
        # rollup
        b = self.rollup[bucket]
        b["included"] += int(included)
        b["excluded"] += int(excluded)
        b["conflicts"] += int(conflicts)
        if reasons:
            for k, v in reasons.items():
                b["reasons"][k] = b["reasons"].get(k, 0) + int(v)

    def set_final_included(self, n: int) -> None:
        """
        Explicitly set the final included count (optional).
        If not set, end_run() will infer from the last screening phase that ran.
        """
        self.rollup["final_included"] = int(n)

    def log_export(self, outputs: Dict[str, Any], message: Optional[str] = None) -> None:
        """
        Record that results/logs were exported (paths, counts, etc.).
        """
        msg = message or "Export completed."
        self._append_event(
            step=PrismaStep.EXPORT,
            event_type=EventType.EXPORT,
            level=LogLevel.INFO,
            message=msg,
            payload={"outputs": outputs},
        )

    def log_warning(self, step: PrismaStep, message: str, payload: Optional[Dict[str, Any]] = None) -> None:
        """Emit a WARNING event with message and optional payload."""
        self._append_event(step=step, event_type=EventType.WARNING, level=LogLevel.WARNING,
                           message=message, payload=payload or {})

    def log_error(self, step: PrismaStep, message: str, payload: Optional[Dict[str, Any]] = None) -> None:
        """Emit an ERROR event with message and optional payload."""
        self._append_event(step=step, event_type=EventType.ERROR, level=LogLevel.ERROR,
                           message=message, payload=payload or {})

    # --------------------------- export ----------------------------------------

    def to_json(self) -> str:
        """
        Return a full JSON document with header, events, and rollup.
        """
        doc = {"header": self.header, "events": self.events, "rollup": self.rollup}
        return json.dumps(doc, indent=2, ensure_ascii=False)

    def save_json(self, path: str) -> None:
        """Persist the full JSON log to disk."""
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.to_json())

    def save_csv(self, path: str) -> None:
        """
        Save a compact CSV where each row is an event; payload is JSON-serialized.
        """
        fields = [
            "timestamp", "step", "event_type", "level", "message",
            "source_id", "project_id", "run_id", "actor_user_id", "payload",
        ]
        with open(path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            for e in self.events:
                row = {k: e.get(k) for k in fields}
                row["payload"] = json.dumps(row["payload"], ensure_ascii=False)
                writer.writerow(row)

    # --------------------------- PRISMA flow -----------------------------------

    def to_prisma_flow(self) -> Dict[str, Any]:
        """
        Compute PRISMA 2020 flow numbers from the in-memory rollup.

        The duplicates figure follows 'duplicates_reporting_mode':
          - ALL_BEFORE_SCREENING: duplicates = identified_total - records_after_dedup
          - BETWEEN_DATABASES_ONLY: duplicates = dedup_global.removed
            and the remainder (if any) is booked as 'removed_before_screening_other'
            so the arithmetic still balances.

        We also include 'records_with_missing_abstracts' for transparency. This is not a canonical
        PRISMA box in all diagrams but is useful for reproducibility and audit.
        """
        identified_total = int(self.rollup["identified_total"])
        within_total = int(self.rollup["within_source_removed_total"] or 0)
        dg = self.rollup["dedup_global"] or {}
        dg_after = dg.get("after")
        dg_removed = int(dg.get("removed") or 0)

        # Determine records_after_dedup (baseline for TA screening).
        # Preferred: global dedup AFTER value if present; else fallback to identified - within-source removed.
        if dg_after is not None:
            records_after_dedup = int(dg_after)
        else:
            records_after_dedup = max(0, identified_total - within_total)

        mode = self.duplicates_reporting_mode

        if mode == DuplicatesReportingMode.ALL_BEFORE_SCREENING:
            # Count ALL duplicates removed before screening (within + across).
            duplicates_removed = max(0, identified_total - records_after_dedup)
            removed_other = 0
        else:
            # Count ONLY across-sources duplicates; any within-source removals are booked as 'other'.
            duplicates_removed = int(dg_removed or 0)
            removed_other = max(0, (identified_total - records_after_dedup) - duplicates_removed)

        # Screening aggregates
        ab = self.rollup["abstract_screen"]
        ft = self.rollup["fulltext_screen"]

        ta_screened = int(ab["included"]) + int(ab["excluded"])
        ta_excluded = int(ab["excluded"])

        ft_assessed = int(ft["included"]) + int(ft["excluded"])
        ft_excluded = int(ft["excluded"])
        ft_reasons = dict(ft["reasons"])  # already aggregated codes

        # Final included
        final_included = self.rollup["final_included"]
        if final_included is None:
            final_included = ft["included"] if ft_assessed > 0 else ab["included"]

        flow = {
            # Identification
            "records_identified_total": int(identified_total),
            "records_identified_by_source": dict(self.rollup["identified_by_source"]),

            # Duplicates / removed before screening
            "duplicates_removed": int(duplicates_removed),
            "records_removed_before_screening_other": int(removed_other),

            # Remaining for screening
            "records_after_deduplication": int(records_after_dedup),

            # Additional transparency (pre-screening validations)
            "records_with_missing_abstracts": int(self.rollup.get("missing_abstracts_total", 0)),

            # Screening (Title/Abstract)
            "records_screened_title_abstract": int(ta_screened),
            "records_excluded_title_abstract": int(ta_excluded),

            # Eligibility (Full-text)
            "reports_assessed_for_eligibility": int(ft_assessed),
            "reports_excluded_fulltext": int(ft_excluded),
            "reports_excluded_reasons": ft_reasons,

            # Included
            "studies_included_in_review": int(final_included),
        }
        return flow

    # --------------------------- validation ------------------------------------

    def validate_rollup(self) -> List[str]:
        """
        Run basic arithmetic sanity checks; returns a list of warning messages.
        Also emits WARNING events for traceability.
        """
        warnings: List[str] = []
        identified_total = int(self.rollup["identified_total"])
        dg = self.rollup["dedup_global"]
        dg_before, dg_after, dg_removed = dg.get("before"), dg.get("after"), dg.get("removed")

        # 1) Global dedup consistency
        if dg_before is not None and dg_after is not None:
            if int(dg_after) > int(dg_before):
                msg = "Global dedup: 'after' exceeds 'before'."
                warnings.append(msg)
                self.log_warning(PrismaStep.DEDUP_MERGED, msg, payload={"before": dg_before, "after": dg_after})

        # 2) Merge vs inputs (only if 'merged_before_global_dedup' present)
        merged_before = self.rollup["merged_before_global_dedup"]
        if merged_before is not None and merged_before > identified_total:
            msg = "Merged-before-global-dedup exceeds identified total."
            warnings.append(msg)
            self.log_warning(PrismaStep.MERGE, msg, payload={"merged_before": merged_before, "identified_total": identified_total})

        # 3) PRISMA balance check depending on reporting mode
        flow = self.to_prisma_flow()
        lhs = flow["records_identified_total"] - (flow["duplicates_removed"] + flow["records_removed_before_screening_other"])
        rhs = flow["records_after_deduplication"]
        if lhs != rhs:
            msg = "PRISMA arithmetic mismatch: identified - removed != after_dedup."
            warnings.append(msg)
            self.log_warning(PrismaStep.DEDUP_MERGED, msg, payload={"lhs": lhs, "rhs": rhs, "flow": flow})

        # 4) TA screened must not exceed 'after_deduplication'
        ta_screened = flow["records_screened_title_abstract"]
        if ta_screened > flow["records_after_deduplication"]:
            msg = "More records screened at Title/Abstract than available after deduplication."
            warnings.append(msg)
            self.log_warning(PrismaStep.SCREEN_ABSTRACT, msg, payload={
                "screened": ta_screened,
                "after_dedup": flow["records_after_deduplication"]
            })

        # 5) Full-text assessed vs TA-included (heuristic; depends on pipeline rules)
        ft_assessed = flow["reports_assessed_for_eligibility"]
        if ft_assessed > (self.rollup["abstract_screen"]["included"] or 0):
            # Not always an error (you may add extra FT material), so warning only.
            msg = "Full-text assessed exceeds TA-included (check pipeline rules or supplementary inputs)."
            warnings.append(msg)
            self.log_warning(PrismaStep.SCREEN_FULLTEXT, msg, payload={
                "ft_assessed": ft_assessed,
                "ta_included": self.rollup["abstract_screen"]["included"]
            })

        return warnings

    # --------------------------- internals -------------------------------------

    def _append_event(
        self,
        step: PrismaStep,
        event_type: EventType,
        level: LogLevel,
        message: str,
        payload: Dict[str, Any],
        source_id: Optional[str] = None,
    ) -> None:
        """
        Append a single immutable event to the audit trail and (optionally) write to DB.
        """
        ev = {
            "event_id": str(uuid.uuid4()),
            "project_id": self.project_id,
            "run_id": self.run_id,
            "timestamp": _utc_now_iso(),
            "actor_user_id": self.user_id,

            "step": str(step),
            "event_type": str(event_type),
            "level": str(level),

            "message": message,
            "source_id": source_id,
            "payload": payload,

            # For idempotency: if you need to protect a block against duplicates,
            # you can pass a correlation_id in payload and move it up here.
            "correlation_id": str(uuid.uuid4()),
        }
        self.events.append(ev)
        self._write_event_to_supabase(ev)

    def _write_run_row_to_supabase(self, status: str, message: Optional[str] = None) -> None:
        """
        Upsert a run row with current summary (only if a Supabase client is configured).

        Important:
        - This method must never call _append_event(...) on failure, to avoid recursive
          logging loops when the prisma_* tables are missing or misconfigured.
        """
        if not self.supabase or not self.run_id:
            return
        summary = self.to_prisma_flow() if status in (RunStatus.COMPLETED.value, RunStatus.FAILED.value, RunStatus.CANCELED.value) else None
        row = {
            "id": self.run_id,
            "project_id": self.project_id,
            "status": status,
            "started_at": self.header.get("run_started_at"),
            "ended_at": self.header.get("run_ended_at"),
            "framework": self.header.get("framework"),
            "criteria": self.header.get("criteria"),
            "objectives": self.header.get("objectives"),
            "mode": self.header.get("mode"),
            "llm": self.header.get("llm"),
            "summary": summary,
            "message": message,
            "created_at": _utc_now_iso(),
        }
        try:
            # Expect a table "prisma_runs" with PK (id uuid).
            self.supabase.table("prisma_runs").upsert(row).execute()
        except Exception as e:
            # Avoid recursion: only write to Python logs.
            LOG.warning("Supabase upsert(prisma_runs) failed: %s", e, exc_info=True)

    def _write_event_to_supabase(self, event: Dict[str, Any]) -> None:
        """
        Insert the event into 'prisma_events' (only if a Supabase client is configured).

        Important:
        - This method must never call _append_event(...) on failure, to avoid recursive
          logging loops when the prisma_* tables are missing or misconfigured.
        """
        if not self.supabase:
            return
        try:
            # Expect a table "prisma_events" with PK (event_id uuid).
            self.supabase.table("prisma_events").insert(event).execute()
        except Exception as e:
            # Avoid recursion: only write to Python logs.
            LOG.warning("Supabase insert(prisma_events) failed: %s", e, exc_info=True)