# core/preflight.py
# -*- coding: utf-8 -*-
"""
Preflight checks for uploaded bibliographic files (RIS/BIB).

This module is UI-agnostic and safe to reuse from Streamlit pages and in the worker.
It parses files via your BibliographicConverter, computes lightweight metrics,
and returns machine-readable results (status + issue codes). Actual i18n is done in the UI.
"""

from __future__ import annotations
import os
import tempfile
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple
import zipfile

import pandas as pd

from core.file_handler import BibliographicConverter
from core.enums import PreflightStatus, PreflightIssueCode
from utils.helpers import extract_text_from_pdf_bytes


@dataclass(frozen=True)
class PreflightConfig:
    """
    Configuration for preflight validation.

    Attributes
    ----------
    allowed_types : set[str]
        File types accepted for parsing, e.g., {"ris", "bib"}.
    abstract_column_candidates : tuple[str, ...]
        Column names to probe for abstract content.
    min_abstract_ratio_warn : float
        If (with_abstract / total) is below this threshold in ABSTRACT mode,
        we return a WARNING (but do not block).
    """
    allowed_types: set[str] = field(default_factory=lambda: {"ris", "bib", "nbib", "zip"})
    abstract_column_candidates: Tuple[str, ...] = (
        "abstract", "AB", "N2", "Abstract", "ABSTRACT", "abstract_text"
    )
    min_abstract_ratio_warn: float = 0.60


@dataclass
class PreflightFileResult:
    """
    Result of a single-file preflight analysis.

    Notes
    -----
    - `message_keys` are *not* human-readable strings; the UI maps them via i18n.
    - `issues` are machine-readable codes to reason about the state.
    """
    filename: str
    file_type: str
    label: str

    records_total: int = 0
    records_with_abstract: int = 0

    status: PreflightStatus = PreflightStatus.OK
    issues: List[PreflightIssueCode] = field(default_factory=list)
    message_keys: List[str] = field(default_factory=list)

    parse_error: Optional[str] = None


class PreflightService:
    """
    Stateless service to perform preflight checks on uploaded files.

    The service:
    - writes the uploaded file to a temp path,
    - parses via `BibliographicConverter`,
    - counts records and abstract coverage,
    - decides `status` and `issues` based on the chosen review `mode`.
    """

    def __init__(self, config: Optional[PreflightConfig] = None) -> None:
        self.cfg = config or PreflightConfig()

    # ──────────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────────
    def analyze_uploaded_file(self, uploaded_file, label: str, mode: str) -> PreflightFileResult:
        """
        Analyze a single Streamlit UploadedFile (or file-like).

        Parameters
        ----------
        uploaded_file :
            Streamlit's UploadedFile; exposes .name and .getbuffer().
        label : str
            User-provided free-text label (e.g., "MEDLINE", "EMBASE").
        mode : str
            "Abstract" or "Fulltext" (case-insensitive).

        Returns
        -------
        PreflightFileResult
        """
        suffix = os.path.splitext(uploaded_file.name)[1].lower()
        file_type = suffix.lstrip(".")
        res = PreflightFileResult(filename=uploaded_file.name, file_type=file_type, label=label)

        if file_type not in self.cfg.allowed_types:
            res.status = PreflightStatus.ERROR
            res.issues.append(PreflightIssueCode.UNSUPPORTED_TYPE)
            res.message_keys.append("preflight.status.error_unparseable")
            return res

        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        try:
            # Persist to disk so the converter can read it
            tmp.write(uploaded_file.getbuffer())
            tmp.flush()
            tmp.close()

            # Parse data (RIS/BIB) or scan ZIP of PDFs
            if file_type == "zip":
                total_pdfs = 0
                readable = 0
                try:
                    with zipfile.ZipFile(tmp.name) as zf:
                        for name in zf.namelist():
                            # Skip directories and macOS resource forks
                            if name.endswith("/"):
                                continue
                            if name.startswith("__MACOSX/"):
                                continue
                            base = os.path.basename(name)
                            if base.startswith("._"):
                                continue
                            if not base.lower().endswith(".pdf"):
                                continue
                            total_pdfs += 1
                            # For up to 10 PDFs, try text extraction as a readability proxy
                            if readable < 10:
                                try:
                                    pdf_bytes = zf.read(name)
                                    text = extract_text_from_pdf_bytes(pdf_bytes)
                                    if (text or "").strip():
                                        readable += 1
                                except Exception:
                                    # Ignore per-file extraction issues in preflight
                                    pass
                except zipfile.BadZipFile as e:
                    raise e

                res.records_total = int(total_pdfs)
                res.records_with_abstract = int(readable)
            else:
                conv = BibliographicConverter(tmp.name, file_type=file_type)
                df = conv.to_dataframe()
                res.records_total = int(len(df))
                res.records_with_abstract = int(self._count_with_abstract(df))

            # Decide status based on mode
            mode_lower = (mode or "").strip().lower()
            if res.records_total == 0:
                res.status = PreflightStatus.ERROR
                res.issues.append(PreflightIssueCode.NO_RECORDS)
                res.message_keys.append("preflight.status.error_no_records")
                return res

            if "abstract" in mode_lower:
                # Abstract screening: require abstracts
                if res.records_with_abstract == 0:
                    res.status = PreflightStatus.ERROR
                    res.issues.append(PreflightIssueCode.NO_ABSTRACTS)
                    res.message_keys.append("preflight.status.error_no_abstracts")
                else:
                    ratio = res.records_with_abstract / max(1, res.records_total)
                    if ratio < self.cfg.min_abstract_ratio_warn:
                        res.status = PreflightStatus.WARNING
                        res.issues.append(PreflightIssueCode.LOW_ABSTRACT_RATIO)
                        res.message_keys.append("preflight.status.warn_low_abstracts")
                    else:
                        res.status = PreflightStatus.OK
                        res.message_keys.append("preflight.status.ok")
            else:
                # Fulltext mode: minimal checks
                res.status = PreflightStatus.OK
                res.message_keys.append("preflight.status.ok")

            return res

        except Exception as e:
            res.status = PreflightStatus.ERROR
            res.issues.append(PreflightIssueCode.PARSE_FAILED)
            res.message_keys.append("preflight.status.error_unparseable")
            res.parse_error = str(e)
            return res

        finally:
            try:
                os.remove(tmp.name)
            except Exception:
                pass

    def analyze_many(self, uploaded_files: Sequence, labels: Sequence[str], mode: str) -> List[PreflightFileResult]:
        """
        Analyze multiple files in one call.
        """
        results: List[PreflightFileResult] = []
        for f, lbl in zip(uploaded_files, labels):
            results.append(self.analyze_uploaded_file(f, lbl, mode))
        return results

    # ──────────────────────────────────────────────────────────────────────
    # Internals
    # ──────────────────────────────────────────────────────────────────────
    def _count_with_abstract(self, df: pd.DataFrame) -> int:
        """
        Count rows that have a non-empty abstract field.
        """
        if df is None or df.empty:
            return 0
        for col in self.cfg.abstract_column_candidates:
            if col in df.columns:
                series = df[col].fillna("").astype(str).str.strip()
                return int((series != "").sum())
        return 0
