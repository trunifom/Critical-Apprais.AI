"""
LiteratureDatabase
------------------
Container for a single bibliographic dataset (e.g., PubMed export) with:
- a pandas DataFrame holding the records,
- source metadata (label, original file name, import time),
- non-destructive status columns for PRISMA transparency (duplicates, missing abstracts),
- convenience methods to mark duplicates and missing abstracts,
- helper to obtain a filtered view for LLM processing.

Key principles:
- No rows are deleted in this class. Duplicates and invalid entries are marked.
- A stable per-row identifier (study_uid) is ensured for deterministic re-alignment of results.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional, List, Tuple, Dict

import pandas as pd


# ----------------------------- Defaults / Conventions -------------------------------

DEFAULT_ABSTRACT_COLUMN = "abstract"
DEFAULT_TITLE_COLUMN = "title"
DEFAULT_AUTHORS_COLUMN = "authors"
DEFAULT_DOI_COLUMN = "doi"
DEFAULT_PMID_COLUMN = "pmid"

STATUS_COLUMNS = [
    "study_uid",         # stable identifier for each row
    "is_duplicate",      # True if marked as duplicate
    "duplicate_of",      # study_uid of the kept record this row duplicates
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


def _choose_duplicate_mask(
    df: pd.DataFrame,
    subset: Optional[List[str]],
    strategy: str,
    keep: str,
) -> Tuple[pd.Series, List[str]]:
    """
    Compute a boolean mask marking duplicates according to the chosen logic.
    Returns the mask and the effective subset columns used for grouping.
    - keep follows pandas semantics: 'first' or 'last'.
    - If subset is provided and the columns exist, it overrides the strategy.
    """
    # Explicit subset takes precedence if all or some exist
    if subset:
        subset_existing = [c for c in subset if c in df.columns]
        if subset_existing:
            mask = df.duplicated(subset=subset_existing, keep=keep)
            return mask, subset_existing

    strategy = (strategy or "doi_or_title").lower()

    if strategy == "strict_ids":
        # Use only strict identifiers (e.g., DOI/PMID)
        candidates = [c for c in [DEFAULT_DOI_COLUMN, DEFAULT_PMID_COLUMN] if c in df.columns]
        if candidates:
            mask = df.duplicated(subset=candidates, keep=keep)
            return mask, candidates
        return pd.Series([False] * len(df), index=df.index), candidates

    if strategy == "title_authors":
        # Use title + authors when both exist, otherwise fall back to title
        pair = [c for c in [DEFAULT_TITLE_COLUMN, DEFAULT_AUTHORS_COLUMN] if c in df.columns]
        if pair:
            return df.duplicated(subset=pair, keep=keep), pair
        if DEFAULT_TITLE_COLUMN in df.columns:
            return df.duplicated(subset=[DEFAULT_TITLE_COLUMN], keep=keep), [DEFAULT_TITLE_COLUMN]
        return pd.Series([False] * len(df), index=df.index), []

    if strategy == "title":
        if DEFAULT_TITLE_COLUMN in df.columns:
            return df.duplicated(subset=[DEFAULT_TITLE_COLUMN], keep=keep), [DEFAULT_TITLE_COLUMN]
        return pd.Series([False] * len(df), index=df.index), []

    # default: "doi_or_title"
    if DEFAULT_DOI_COLUMN in df.columns:
        doi_series = _safe_str_series(df[DEFAULT_DOI_COLUMN])
        valid_mask = doi_series.str.strip().ne("")
        dup_mask = pd.Series(False, index=df.index)
        if valid_mask.any():
            dup_mask.loc[valid_mask] = doi_series.loc[valid_mask].duplicated(keep=keep).values
        if dup_mask.any():
            return dup_mask, [DEFAULT_DOI_COLUMN]

    if DEFAULT_TITLE_COLUMN in df.columns:
        return df.duplicated(subset=[DEFAULT_TITLE_COLUMN], keep=keep), [DEFAULT_TITLE_COLUMN]

    return pd.Series([False] * len(df), index=df.index), []


# ----------------------------- Main class -------------------------------------------


class LiteratureDatabase:
    """
    Represents a single bibliographic dataset (e.g., from PubMed or PsycINFO),
    including its data as a pandas DataFrame and metadata about the source and upload.

    This class does not parse files itself – it expects to receive a pre-parsed DataFrame.
    It adds PRISMA-friendly status columns and provides non-destructive marking operations.
    """

    def __init__(
        self,
        label: str,
        dataframe: pd.DataFrame,
        user_defined_source: Optional[str] = None,
        source_file_name: Optional[str] = None,
        import_time: Optional[datetime] = None,
    ) -> None:
        """
        Initialize a LiteratureDatabase object.

        :param label: Internal system label for the dataset (e.g. "PubMed_Export_2025_08_05")
        :param dataframe: Parsed DataFrame containing the bibliographic entries
        :param user_defined_source: Free-text source description (e.g. "PubMed July 2025")
        :param source_file_name: Original uploaded file name (e.g. "export.bib")
        :param import_time: Timestamp when the file was uploaded; defaults to current UTC time
        """
        self.label = label
        self.df = dataframe.copy()

        # User-facing metadata
        self.user_defined_source = user_defined_source or "Unknown source"
        self.source_file_name = source_file_name or "unnamed_file"
        self.import_time = import_time or datetime.utcnow()

        # Ensure status columns exist on initialization
        _ensure_status_columns(self.df)

        # Statistics for transparency
        self.original_size = len(self.df)          # number of entries in the original file
        self.duplicates_marked = 0                 # how many duplicates have been marked (non-destructive)
        self.missing_abstracts_marked = 0          # how many records were marked as missing abstracts
        self.filtered = False                      # indicates if the dataset was filtered (e.g., after screening)

    # ----------------------------- Marking operations ------------------------------

    def mark_duplicates(
        self,
        subset: Optional[List[str]] = None,
        strategy: str = "doi_or_title",
        keep: str = "first",
    ) -> int:
        """
        Mark duplicate entries in the DataFrame (non-destructive).
        - sets is_duplicate=True
        - sets exclusion_reason='DUPLICATE' where not already set
        - sets duplicate_of to the study_uid of the kept record

        :param subset: Explicit columns to consider; overrides strategy if provided and existing
        :param strategy: One of {"doi_or_title", "strict_ids", "title", "title_authors"}
        :param keep: 'first' (default) or 'last' – keeper selection rule
        :return: Number of rows newly marked as duplicates
        """
        _ensure_status_columns(self.df)

        dupe_mask, used_subset = _choose_duplicate_mask(self.df, subset, strategy, keep)
        if len(self.df) == 0 or int(dupe_mask.sum()) == 0:
            return 0

        # Mark duplicates
        self.df.loc[dupe_mask, "is_duplicate"] = True

        # Set exclusion reason only if not yet set
        needs_reason = dupe_mask & self.df["exclusion_reason"].isna()
        self.df.loc[needs_reason, "exclusion_reason"] = "DUPLICATE"

        # Assign 'duplicate_of' pointers
        if used_subset:
            grouping_cols = used_subset
            grouped = self.df.reset_index(drop=False).groupby(grouping_cols, dropna=False)
        else:
            # Fallback to normalized title grouping
            self.df["_normalized_title_tmp"] = _normalized_title_series(self.df)
            grouped = self.df.reset_index(drop=False).groupby("_normalized_title_tmp", dropna=False)

        for _, group in grouped:
            if len(group) <= 1:
                continue

            # Determine keeper according to 'keep'
            if keep == "last":
                keeper = group.iloc[-1]
                duplicate_members = group.index[:-1]
            else:
                keeper = group.iloc[0]
                duplicate_members = group.index[1:]

            keeper_row_idx = keeper["index"]  # back to original df index
            keeper_uid = self.df.loc[keeper_row_idx, "study_uid"]

            # Only set duplicate_of for rows actually marked as duplicates
            for grp_pos in duplicate_members:
                row_idx = group.loc[grp_pos, "index"]
                if bool(self.df.loc[row_idx, "is_duplicate"]):
                    self.df.loc[row_idx, "duplicate_of"] = keeper_uid

        if "_normalized_title_tmp" in self.df.columns:
            self.df.drop(columns=["_normalized_title_tmp"], inplace=True)

        newly_marked = int(dupe_mask.sum())
        self.duplicates_marked += newly_marked
        return newly_marked

    def mark_missing_abstracts(self, abstract_column: str = DEFAULT_ABSTRACT_COLUMN) -> int:
        """
        Mark records with missing/empty abstracts (non-destructive):
        - sets has_abstract=False,
        - sets exclusion_reason='NO_ABSTRACT' where not already set,
        - sets exclusion_details with a short explanation.

        :param abstract_column: Column name containing the abstract text
        :return: Number of rows newly marked as missing abstracts
        """
        _ensure_status_columns(self.df)

        # If the abstract column is entirely missing, treat all as missing
        if abstract_column not in self.df.columns:
            if len(self.df) == 0:
                return 0
            self.df["has_abstract"] = False
            update_mask = self.df["exclusion_reason"].isna()
            self.df.loc[update_mask, "exclusion_reason"] = "NO_ABSTRACT"
            self.df.loc[update_mask, "exclusion_details"] = "abstract column missing"
            newly_marked = int(update_mask.sum())
            self.missing_abstracts_marked += newly_marked
            return newly_marked

        series = _safe_str_series(self.df[abstract_column])
        missing_mask = series.str.strip().eq("")
        if int(missing_mask.sum()) == 0:
            return 0

        self.df.loc[missing_mask, "has_abstract"] = False

        to_update = missing_mask & self.df["exclusion_reason"].isna()
        self.df.loc[to_update, "exclusion_reason"] = "NO_ABSTRACT"
        self.df.loc[to_update, "exclusion_details"] = "empty or whitespace-only abstract"

        newly_marked = int(missing_mask.sum())
        self.missing_abstracts_marked += newly_marked
        return newly_marked

    # ----------------------------- Legacy compatibility ----------------------------

    def remove_duplicates(self, subset: Optional[List[str]] = None) -> int:
        """
        Deprecated destructive API retained for compatibility. It no longer deletes rows.
        Calls mark_duplicates(...) and returns the number of rows marked as duplicates.

        :param subset: List of column names to consider for duplicate detection.
                       Defaults to ["title", "authors"] if not specified.
        :return: Number of entries that were marked as duplicates
        """
        if subset is None:
            subset = [DEFAULT_TITLE_COLUMN, DEFAULT_AUTHORS_COLUMN]
        return self.mark_duplicates(subset=subset, strategy="title_authors", keep="first")

    # ----------------------------- Views / Accessors --------------------------------

    def filter_valid_for_llm(self) -> Tuple[pd.DataFrame, pd.Index]:
        """
        Return a filtered view suitable for LLM processing:
        - excludes duplicates,
        - excludes records with missing abstracts,
        - excludes records with any exclusion_reason set (conservative).
        Returns both the filtered DataFrame (copy) and the original index positions.
        """
        _ensure_status_columns(self.df)
        mask = (~self.df["is_duplicate"]) & (self.df["has_abstract"]) & (self.df["exclusion_reason"].isna())
        filtered = self.df.loc[mask].copy()
        return filtered, filtered.index

    def get_dataframe(self) -> pd.DataFrame:
        """
        Return a copy of the current DataFrame. External mutation is discouraged.
        """
        return self.df.copy()

    def get_metadata(self) -> Dict[str, object]:
        """
        Return all metadata about this dataset, useful for logging or JSON export.
        """
        return {
            "label": self.label,
            "user_defined_source": self.user_defined_source,
            "source_file_name": self.source_file_name,
            "import_time": self.import_time.isoformat(),
            "original_size": self.original_size,
            "current_size": len(self.df),
            "duplicates_marked": self.duplicates_marked,
            "missing_abstracts_marked": self.missing_abstracts_marked,
            "filtered": self.filtered,
        }

    def set_filtered_flag(self, value: bool = True) -> None:
        """
        Set the 'filtered' flag to indicate whether this dataset has been processed
        in screening steps.
        """
        self.filtered = bool(value)

    def preview(self, n: int = 5) -> pd.DataFrame:
        """
        Return a preview of the top N entries of the dataset.
        """
        return self.df.head(int(n))

    def __repr__(self) -> str:
        """
        Developer-friendly string representation.
        """
        return (
            f"<LiteratureDatabase {self.label} | "
            f"Entries: {len(self.df)} | "
            f"Duplicates marked: {self.duplicates_marked} | "
            f"Missing abstracts: {self.missing_abstracts_marked} | "
            f"Filtered: {self.filtered}>"
        )
    