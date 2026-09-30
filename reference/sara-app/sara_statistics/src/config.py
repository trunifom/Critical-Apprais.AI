"""
Central configuration for statistics utilities.

Having a dedicated module keeps paths and column names consistent across
scripts and makes it easy to extend the toolkit to additional projects.
"""

from pathlib import Path

# Base directory corresponds to the repository root (two levels up from this file)
BASE_DIR = Path(__file__).resolve().parents[2]

# Data input root (each project lives under data/project-XX_name)
DATA_DIR = BASE_DIR / "data"

# Output root for statistical reports
REPORT_DIR = BASE_DIR / "sara_statistics" / "reports"

# Column settings used by the test–retest script
ID_COL = "study_uid"
LABEL_COL = "label"

# Default glob pattern for run files (can be overridden if future formats differ)
RUN_FILE_PATTERN = "*_run-*.csv"

