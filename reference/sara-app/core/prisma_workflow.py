"""
PRISMAWorkflow
--------------
Central orchestration of a PRISMA-compliant review workflow across one or multiple
bibliographic sources (LiteratureDatabase). The workflow:
- manages input sources,
- merges sources into a single dataset,
- marks (instead of deleting) duplicates,
- marks records with missing abstracts,
- provides a filtered view for LLM processing,
- writes snapshots of the merged data for auditability.

Key principles:
- No rows are deleted. Duplicates and empty abstracts are marked to maintain scientific
  transparency and reproducibility.
- Markings are stored in explicit status columns (e.g., is_duplicate, has_abstract, exclusion_reason).
- A stable per-row identifier (study_uid) is ensured to support deterministic re-alignment
  of LLM results back to the original dataset.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Tuple, Dict

import pandas as pd

from core.literature_database import LiteratureDatabase


# ----------------------------- Configuration / Defaults -----------------------------


@dataclass(frozen=True)
class DedupConfig:
    """
    Configuration for duplicate marking.

    strategy:
        - "doi_or_title": prefer DOI (if present and non-empty), otherwise title
        - "strict_ids": rely only on strict identifiers (e.g., DOI/PMID), otherwise no dupes
        - "title": title only
        - "title_authors": title and authors
    keep:
        - same semantics as pandas.DataFrame.duplicated(): 'first' or 'last'
    subset:
        - if explicitly provided (and columns exist), overrides the strategy
    """
    strategy: str = "doi_or_title"
    keep: str = "first"
    subset: Optional[List[str]] = None


DEFAULT_ABSTRACT_COLUMN = "abstract"
DEFAULT_TITLE_COLUMN = "title"
DEFAULT_AUTHORS_COLUMN = "authors"
DEFAULT_DOI_COLUMN = "doi"
DEFAULT_PMID_COLUMN = "pmid"

STATUS_COLUMNS = [
    "study_uid",         # stable identifier for each row
    "is_duplicate",      # True if marked as duplicate
    "duplicate_of",      # study_uid of the keeper this row duplicates
    "has_abstract",      # True if abstract exists and is not empty
    "exclusion_reason",  # e.g., "DUPLICATE", "NO_ABSTRACT"
    "exclusion_details", # optional human-readable details
]


# ----------------------------- Helper functions -------------------------------------


def _ensure_status_columns(df: pd.DataFrame) -> None:
    """
    Ensure all status columns exist; create them if missing.

    - study_uid is created as a UUID4 string per row if absent.
    - other status columns are initialized with sensible defaults.
    """
    if "study_uid" not in df.columns:
        # Insert at column 0 so it is easy to spot in exports
        df.insert(0, "study_uid", [str(uuid.uuid4()) for _ in range(len(df))])

    if "is_duplicate" not in df.columns:
        df["is_duplicate"] = False

    if "duplicate_of" not in df.columns:
        df["duplicate_of"] = pd.Series([None] * len(df), dtype="object")

    if "has_abstract" not in df.columns:
        df["has_abstract"] = True

    if "exclusion_reason" not in df.columns:
        df["exclusion_reason"] = pd.Series([None] * len(df), dtype="object")

    if "exclusion_details" not in df.columns:
        df["exclusion_details"] = pd.Series([None] * len(df), dtype="object")


def _safe_str_series(series: pd.Series) -> pd.Series:
    """
    Return a string-typed series suitable for string operations:
    - replace NaN/None with empty strings,
    - cast to pandas 'string' dtype.
    """
    return series.fillna("").astype("string") if isinstance(series, pd.Series) else pd.Series([], dtype="string")


def _normalized_title_series(df: pd.DataFrame, title_col: str = DEFAULT_TITLE_COLUMN) -> pd.Series:
    """
    Create a normalized title series (lowercased, trimmed, simple punctuation removal).
    Useful as a heuristic for grouping titles; not a fuzzy match.
    """
    if title_col not in df.columns:
        return pd.Series([""] * len(df), dtype="string")
    s = _safe_str_series(df[title_col])
    s = s.str.lower()
    s = s.str.replace(r"[^\w\s]", "", regex=True)  # remove punctuation
    s = s.str.replace(r"\s+", " ", regex=True).str.strip()
    return s


def _choose_duplicate_mask(df: pd.DataFrame, config: DedupConfig) -> Tuple[pd.Series, List[str]]:
    """
    Compute a boolean mask marking duplicates according to the chosen strategy.
    Returns the mask and the effective subset columns used for grouping.
    The 'keep' behavior is taken from config.keep ('first' or 'last').

    Note: For DOI-based matching, empty DOIs are ignored to avoid false positives.
    """
    # If a subset is explicitly provided and columns exist, use it
    if config.subset:
        subset_existing = [c for c in config.subset if c in df.columns]
        if subset_existing:
            mask = df.duplicated(subset=subset_existing, keep=config.keep)
            return mask, subset_existing

    strategy = (config.strategy or "doi_or_title").lower()

    if strategy == "strict_ids":
        candidates = [c for c in [DEFAULT_DOI_COLUMN, DEFAULT_PMID_COLUMN] if c in df.columns]
        if candidates:
            mask = df.duplicated(subset=candidates, keep=config.keep)
            return mask, candidates
        return pd.Series([False] * len(df), index=df.index), candidates

    if strategy == "title_authors":
        subset = [c for c in [DEFAULT_TITLE_COLUMN, DEFAULT_AUTHORS_COLUMN] if c in df.columns]
        if subset:
            mask = df.duplicated(subset=subset, keep=config.keep)
            return mask, subset
        # fall back to title-only if authors are missing
        if DEFAULT_TITLE_COLUMN in df.columns:
            return df.duplicated(subset=[DEFAULT_TITLE_COLUMN], keep=config.keep), [DEFAULT_TITLE_COLUMN]
        return pd.Series([False] * len(df), index=df.index), []

    if strategy == "title":
        if DEFAULT_TITLE_COLUMN in df.columns:
            return df.duplicated(subset=[DEFAULT_TITLE_COLUMN], keep=config.keep), [DEFAULT_TITLE_COLUMN]
        return pd.Series([False] * len(df), index=df.index), []

    # default: "doi_or_title"
    if DEFAULT_DOI_COLUMN in df.columns:
        doi_series = _safe_str_series(df[DEFAULT_DOI_COLUMN])
        valid_mask = doi_series.str.strip().ne("")
        dup_mask = pd.Series(False, index=df.index)
        # Only compute duplicated on rows with a non-empty DOI
        if valid_mask.any():
            dup_mask.loc[valid_mask] = doi_series.loc[valid_mask].duplicated(keep=config.keep).values
        if dup_mask.any():
            return dup_mask, [DEFAULT_DOI_COLUMN]
        # Fallback to title if no DOI duplicates found
    if DEFAULT_TITLE_COLUMN in df.columns:
        return df.duplicated(subset=[DEFAULT_TITLE_COLUMN], keep=config.keep), [DEFAULT_TITLE_COLUMN]

    return pd.Series([False] * len(df), index=df.index), []


def _mark_duplicates_inplace(df: pd.DataFrame, config: DedupConfig) -> int:
    """
    Mark duplicates in-place:
    - sets is_duplicate=True,
    - sets exclusion_reason='DUPLICATE' if not already set,
    - sets duplicate_of to the study_uid of the kept record.
    Never deletes rows. Returns the number of rows newly marked as duplicates.
    """
    _ensure_status_columns(df)

    # Determine duplicate mask and the subset used to group records
    dupe_mask, used_subset = _choose_duplicate_mask(df, config)
    if not len(df) or int(dupe_mask.sum()) == 0:
        return 0

    # Set is_duplicate
    df.loc[dupe_mask, "is_duplicate"] = True

    # Set exclusion_reason only where not yet set
    needs_reason = dupe_mask & df["exclusion_reason"].isna()
    df.loc[needs_reason, "exclusion_reason"] = "DUPLICATE"

    # Determine 'duplicate_of' pointers
    # Group by subset or a normalized title fallback if no subset could be established
    if used_subset:
        grouping_cols = used_subset
        grouped = df.reset_index(drop=False).groupby(grouping_cols, dropna=False)
    else:
        df["_normalized_title_tmp"] = _normalized_title_series(df)
        grouped = df.reset_index(drop=False).groupby("_normalized_title_tmp", dropna=False)

    for _, group in grouped:
        if len(group) <= 1:
            continue
        # Determine keeper according to the 'keep' policy
        if config.keep == "last":
            keeper = group.iloc[-1]
            duplicate_members = group.index[:-1]
        else:
            keeper = group.iloc[0]
            duplicate_members = group.index[1:]

        keeper_row_idx = keeper["index"]  # original df index
        keeper_uid = df.loc[keeper_row_idx, "study_uid"]

        # Assign duplicate_of only to rows that are actually marked as duplicates
        for grp_pos in duplicate_members:
            row_idx = group.loc[grp_pos, "index"]
            if bool(df.loc[row_idx, "is_duplicate"]):
                df.loc[row_idx, "duplicate_of"] = keeper_uid

    # Cleanup temporary column if created
    if "_normalized_title_tmp" in df.columns:
        df.drop(columns=["_normalized_title_tmp"], inplace=True)

    return int(dupe_mask.sum())


def _mark_missing_abstracts_inplace(df: pd.DataFrame, abstract_column: str) -> int:
    """
    Mark records with missing/empty abstracts in-place:
    - sets has_abstract=False,
    - sets exclusion_reason='NO_ABSTRACT' (if not already set),
    - adds exclusion_details with a short explanation.
    Returns how many records were marked.
    """
    _ensure_status_columns(df)

    # If the abstract column is not present, treat all as missing
    if abstract_column not in df.columns:
        if len(df) == 0:
            return 0
        df["has_abstract"] = False
        update_mask = df["exclusion_reason"].isna()
        df.loc[update_mask, "exclusion_reason"] = "NO_ABSTRACT"
        df.loc[update_mask, "exclusion_details"] = "abstract column missing"
        return int(update_mask.sum())

    series = _safe_str_series(df[abstract_column])
    missing_mask = series.str.strip().eq("")
    miss_count = int(missing_mask.sum())
    if miss_count == 0:
        return 0

    df.loc[missing_mask, "has_abstract"] = False

    to_update = missing_mask & df["exclusion_reason"].isna()
    df.loc[to_update, "exclusion_reason"] = "NO_ABSTRACT"
    df.loc[to_update, "exclusion_details"] = "empty or whitespace-only abstract"
    return miss_count


# ----------------------------- PRISMAWorkflow ---------------------------------------


class PRISMAWorkflow:
    """
    Orchestrates a PRISMA-compliant workflow across multiple LiteratureDatabase sources.

    Core principles:
    - Do not delete rows; instead, mark status columns for transparency.
    - Ensure a stable study_uid per row to support exact re-alignment of results.
    - Create local snapshots of merged data to aid auditing.

    Typical usage:
    - call add_source() for each imported source,
    - optionally run per-source duplicate/validation marking,
    - call merge_sources(),
    - run global duplicate/missing-abstract marking on the merged dataset,
    - call save_merged_snapshot() to persist.
    """

    def __init__(self, project_label: str, log_dir: str = "logs") -> None:
        """
        Create a new workflow instance.

        :param project_label: Unique identifier for the project (e.g., "Topic_2025-09-01")
        :param log_dir: Base directory to store snapshots/logs for this project
        """
        self.project_label = project_label
        self.log_dir = os.path.join(log_dir, project_label)
        os.makedirs(self.log_dir, exist_ok=True)

        self.sources: List[LiteratureDatabase] = []
        self.merged_database: Optional[LiteratureDatabase] = None
        self.created_at = datetime.utcnow()

    # --------------------------- Source management ----------------------------------

    def add_source(self, db: LiteratureDatabase) -> None:
        """
        Register a source and ensure it contains the expected status columns.
        """
        if not isinstance(db, LiteratureDatabase):
            raise TypeError("add_source expects a LiteratureDatabase instance.")
        _ensure_status_columns(db.df)
        self.sources.append(db)

    # --------------------------- Merge ----------------------------------------------

    def merge_sources(self) -> LiteratureDatabase:
        """
        Concatenate all source DataFrames into a single merged dataset and wrap it
        in a new LiteratureDatabase. A snapshot is written to disk for auditability.

        :return: The newly created LiteratureDatabase for the merged set.
        """
        if not self.sources:
            raise RuntimeError("No sources available to merge. Call add_source() first.")

        # 1) Concatenate sources in-memory
        merged_df = pd.concat([src.df for src in self.sources], ignore_index=True)

        # Ensure status columns exist after concatenation
        _ensure_status_columns(merged_df)

        # 2) Create the encapsulating LiteratureDatabase
        merged_label = f"{self.project_label}_merged"
        merged_db = LiteratureDatabase(
            label=merged_label,
            dataframe=merged_df,
            user_defined_source="MERGED",
            source_file_name=None,
            import_time=datetime.utcnow(),
        )

        # 3) Store in workflow
        self.merged_database = merged_db

        # 4) Persist a snapshot locally (Parquet preferred; fallback to CSV)
        snapshot_path = os.path.join(self.log_dir, "merged.parquet")
        try:
            merged_df.to_parquet(snapshot_path)
        except Exception:
            # Fallback to CSV if parquet engine isn't available
            snapshot_path = os.path.join(self.log_dir, "merged.csv")
            merged_df.to_csv(snapshot_path, index=False)

        return merged_db

    # --------------------------- Duplicate marking (non-destructive) ----------------

    def mark_duplicates_per_source(self, config: Optional[DedupConfig] = None) -> Dict[str, int]:
        """
        Mark duplicates per source (no deletion).

        :param config: DedupConfig; defaults to DOI-or-title with keep='first'
        :return: Mapping source_label -> count of marked duplicates
        """
        if config is None:
            config = DedupConfig()

        results: Dict[str, int] = {}
        for db in self.sources:
            count = _mark_duplicates_inplace(db.df, config=config)
            results[db.label] = count
        return results

    def mark_duplicates_merged(self, config: Optional[DedupConfig] = None) -> int:
        """
        Mark duplicates on the merged dataset (no deletion).

        :param config: DedupConfig; defaults to DOI-or-title with keep='first'
        :return: Count of marked duplicates
        """
        if self.merged_database is None:
            raise RuntimeError("merged_database not set. Call merge_sources() first.")
        if config is None:
            config = DedupConfig()

        return _mark_duplicates_inplace(self.merged_database.df, config=config)

    # --------------------------- Validations ----------------------------------------

    def mark_missing_abstracts_per_source(self, abstract_column: str = DEFAULT_ABSTRACT_COLUMN) -> Dict[str, int]:
        """
        Mark records with missing/empty abstracts per source.

        :param abstract_column: Name of the abstract column
        :return: Mapping source_label -> count of marked records
        """
        results: Dict[str, int] = {}
        for db in self.sources:
            count = _mark_missing_abstracts_inplace(db.df, abstract_column=abstract_column)
            results[db.label] = count
        return results

    def mark_missing_abstracts_merged(self, abstract_column: str = DEFAULT_ABSTRACT_COLUMN) -> int:
        """
        Mark records with missing/empty abstracts in the merged dataset.

        :param abstract_column: Name of the abstract column
        :return: Count of marked records
        """
        if self.merged_database is None:
            raise RuntimeError("merged_database not set. Call merge_sources() first.")
        return _mark_missing_abstracts_inplace(self.merged_database.df, abstract_column=abstract_column)

    # --------------------------- Filtered view for LLM ------------------------------

    def get_valid_records_merged(self, include_status_columns: bool = False) -> Tuple[pd.DataFrame, pd.Index]:
        """
        Return a filtered view of merged records suitable for LLM processing:
        - excludes rows where is_duplicate == True,
        - excludes rows where has_abstract == False,
        - excludes rows where exclusion_reason is set (conservative filter).

        :param include_status_columns: If True, keep status columns in the returned DataFrame;
                                       otherwise, drop them to simplify LLM inputs.
        :return: (filtered DataFrame, original index positions in the merged DataFrame)
        """
        if self.merged_database is None:
            raise RuntimeError("merged_database not set. Call merge_sources() first.")

        df = self.merged_database.df
        _ensure_status_columns(df)

        valid_mask = (~df["is_duplicate"]) & (df["has_abstract"]) & (df["exclusion_reason"].isna())
        filtered = df.loc[valid_mask].copy()
        original_index = filtered.index

        if not include_status_columns:
            drop_cols = [c for c in STATUS_COLUMNS if c in filtered.columns]
            filtered.drop(columns=drop_cols, inplace=True, errors="ignore")

        return filtered, original_index

    # --------------------------- Snapshots / Utilities ------------------------------

    def save_merged_snapshot(self, fmt: str = "parquet") -> str:
        """
        Persist the current merged DataFrame to disk in the chosen format.

        :param fmt: "parquet" or "csv"
        :return: Path to the written file.
        """
        if self.merged_database is None:
            raise RuntimeError("merged_database not set. Cannot snapshot.")

        df = self.merged_database.df
        fmt = fmt.lower()
        if fmt == "parquet":
            path = os.path.join(self.log_dir, "merged.parquet")
            try:
                df.to_parquet(path)
            except Exception:
                # Fallback to CSV if parquet engine isn't available
                path = os.path.join(self.log_dir, "merged.csv")
                df.to_csv(path, index=False)
        elif fmt == "csv":
            path = os.path.join(self.log_dir, "merged.csv")
            df.to_csv(path, index=False)
        else:
            raise ValueError("Unsupported format: choose 'parquet' or 'csv'.")
        return path

    def list_snapshots(self) -> List[str]:
        """
        List all snapshot files in the project log directory.

        :return: Filenames of stored snapshots.
        """
        if not os.path.isdir(self.log_dir):
            return []
        return [f for f in os.listdir(self.log_dir) if f.startswith("merged.")]

    # --------------------------- Representation -------------------------------------

    def __repr__(self) -> str:
        """
        Developer-friendly representation showing key workflow status.
        """
        src_count = len(self.sources)
        merged_info = f"{len(self.merged_database.df)} entries" if self.merged_database else "not yet merged"
        return f"<PRISMAWorkflow project='{self.project_label}' | sources={src_count} | merged={merged_info}>"