"""
Command-line utility to compute test–retest reliability between multiple runs.

Workflow:
1. Pick a project folder inside the global data directory.
2. Load every CSV that follows the *_run-XX naming convention.
3. Merge all runs on the record identifier.
4. Compute pairwise agreement and Cohen's kappa.
5. Interpret the Kappa value.
6. Print results to console and save summary CSV + Text Report with timestamps.
"""

from __future__ import annotations

import argparse
import logging
from datetime import datetime
from itertools import combinations
from pathlib import Path
from typing import List

import pandas as pd
from sklearn.metrics import cohen_kappa_score

from . import config

# Configure logger
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def interpret_kappa(kappa: float) -> str:
    """
    Interpret Cohen's Kappa based on Landis & Koch (1977).
    """
    if kappa < 0:
        return "Poor"
    elif kappa <= 0.20:
        return "Slight"
    elif kappa <= 0.40:
        return "Fair"
    elif kappa <= 0.60:
        return "Moderate"
    elif kappa <= 0.80:
        return "Substantial"
    elif kappa <= 1.0:
        return "Almost Perfect"
    else:
        return "Unknown"


def load_runs(project_dir: Path) -> pd.DataFrame:
    """
    Load and merge every run CSV within the given project directory.
    Includes robust fallback logic for encodings (utf-8, cp1252, latin1)
    and malformed CSVs.
    """
    run_files: List[Path] = sorted(project_dir.glob(config.RUN_FILE_PATTERN))
    if not run_files:
        raise FileNotFoundError(
            f"No files matching {config.RUN_FILE_PATTERN!r} in {project_dir}"
        )

    print(f"   -> Found {len(run_files)} run files.")

    frames: List[pd.DataFrame] = []
    
    # List of encodings to try in order
    encodings_to_try = ['utf-8', 'cp1252', 'latin1']

    for csv_path in run_files:
        run_tag = csv_path.stem.split("_")[-1]  # e.g., run-01
        logger.info(f"Processing: {csv_path.name}...")

        df = None
        last_error = None

        # Try encodings loop
        for encoding in encodings_to_try:
            try:
                # Attempt 1: Fast load with usecols
                df = pd.read_csv(
                    csv_path,
                    sep=';',
                    encoding=encoding,
                    usecols=[config.ID_COL, config.LABEL_COL]
                )
                # If successful, break the encoding loop
                break 
            
            except UnicodeDecodeError:
                # This encoding failed, try the next one silently
                continue
                
            except ValueError as e:
                # Handle "Usecols do not match" error (Parsing issue, not encoding)
                if "Usecols do not match columns" in str(e):
                    logger.warning(f"   Parsing fallback active for {csv_path.name} (using {encoding})")
                    try:
                        # Fallback: Read all columns with current encoding
                        df_full = pd.read_csv(
                            csv_path,
                            sep=';',
                            encoding=encoding
                        )
                        # Check if columns exist
                        if config.ID_COL not in df_full.columns or config.LABEL_COL not in df_full.columns:
                            # If columns are missing, this might be the wrong encoding (garbage output) or bad file
                            # We raise an error to let the loop try the next encoding or fail
                            raise ValueError(f"Columns missing in {encoding} read.")
                        
                        df = df_full[[config.ID_COL, config.LABEL_COL]].copy()
                        break # Success
                    except (UnicodeDecodeError, ValueError):
                        continue # Fallback failed too, try next encoding
                else:
                    # Some other ValueError occurred
                    last_error = e
                    continue

        if df is None:
            error_msg = f"Failed to read {csv_path.name}. Tried encodings: {encodings_to_try}."
            if last_error:
                error_msg += f" Last error: {last_error}"
            raise ValueError(error_msg)

        df = df.rename(columns={config.LABEL_COL: run_tag})
        frames.append(df)

    merged = frames[0]
    for df in frames[1:]:
        merged = merged.merge(df, on=config.ID_COL, how="outer")

    return merged


def compute_pairwise_stats(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute agreement metrics and interpretation for every pair of runs.
    """
    run_cols = [col for col in df.columns if col.startswith("run-")]
    if len(run_cols) < 2:
        raise ValueError("At least two runs are required for test–retest analysis.")

    rows = []
    for run_a, run_b in combinations(run_cols, 2):
        subset = df[[run_a, run_b]].dropna()
        if subset.empty:
            logger.warning("No overlapping records between %s and %s", run_a, run_b)
            continue

        agreement = (subset[run_a] == subset[run_b]).mean()
        kappa = cohen_kappa_score(subset[run_a], subset[run_b])

        rows.append(
            {
                "run1": run_a,
                "run2": run_b,
                "n_overlap": len(subset),
                "percent_agreement": round(agreement, 4),
                "cohen_kappa": round(kappa, 4),
                "interpretation": interpret_kappa(kappa)
            }
        )

    return pd.DataFrame(rows)


def save_reports(project_name: str, stats_df: pd.DataFrame) -> None:
    """
    Save CSV and a text summary report with timestamped filenames.
    Format: YYYYMMDD-HHMM_test-retest-summary_PROJECTNAME.ext
    """
    out_dir = config.REPORT_DIR / project_name
    out_dir.mkdir(parents=True, exist_ok=True)

    # Generate Timestamp
    timestamp = datetime.now().strftime("%Y%m%d-%H%M")
    
    # Base filename
    base_filename = f"{timestamp}_test-retest-summary_{project_name}"

    # 1. Save CSV
    csv_path = out_dir / f"{base_filename}.csv"
    stats_df.to_csv(csv_path, index=False)
    
    # 2. Save Text Report
    txt_path = out_dir / f"{base_filename}.txt"
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(f"Test-Retest Reliability Report\n")
        f.write(f"Project:   {project_name}\n")
        f.write(f"Date:      {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("=" * 80 + "\n\n")
        
        # Summary Statistics
        mean_kappa = stats_df["cohen_kappa"].mean()
        min_kappa = stats_df["cohen_kappa"].min()
        max_kappa = stats_df["cohen_kappa"].max()
        
        f.write("SUMMARY STATISTICS:\n")
        f.write(f"- Total Comparisons: {len(stats_df)}\n")
        f.write(f"- Average Kappa:     {mean_kappa:.4f} ({interpret_kappa(mean_kappa)})\n")
        f.write(f"- Min Kappa:         {min_kappa:.4f}\n")
        f.write(f"- Max Kappa:         {max_kappa:.4f}\n\n")
        
        f.write("DETAILED RESULTS:\n")
        f.write("-" * 80 + "\n")
        # Convert DataFrame to string table
        f.write(stats_df.to_string(index=False))
        f.write("\n" + "-" * 80 + "\n\n")
        
        f.write("INTERPRETATION GUIDE (Landis & Koch, 1977):\n")
        f.write(" < 0.00:    Poor\n")
        f.write(" 0.00-0.20: Slight\n")
        f.write(" 0.21-0.40: Fair\n")
        f.write(" 0.41-0.60: Moderate\n")
        f.write(" 0.61-0.80: Substantial\n")
        f.write(" 0.81-1.00: Almost Perfect\n")

    print(f"\n[SUCCESS] Reports saved:")
    print(f"   CSV: {csv_path.name}")
    print(f"   TXT: {txt_path.name}")
    print(f"   Loc: {out_dir}")


def main(project_name: str) -> None:
    """
    Orchestrate the full test–retest pipeline for the selected project.
    """
    print("\n" + "="*60)
    print(f" SARA STATISTICS: Test-Retest Analysis")
    print(f" Project: {project_name}")
    print("="*60 + "\n")

    project_dir = config.DATA_DIR / project_name
    if not project_dir.exists():
        raise FileNotFoundError(f"Project directory not found: {project_dir}")

    # 1. Load Data
    df_runs = load_runs(project_dir)
    
    # 2. Compute Stats
    print("\nComputing statistics...")
    stats_df = compute_pairwise_stats(df_runs)
    if stats_df.empty:
        logger.warning("No valid run pairs to report for %s", project_name)
        return

    # 3. Console Output
    print("\n" + "-"*80)
    print(f" ANALYSIS RESULTS")
    print("-"*80)
    # Pandas option to show all columns and rows in console
    pd.set_option('display.max_columns', None)
    pd.set_option('display.width', 1000)
    print(stats_df.to_string(index=False))
    print("-"*80)

    # 4. Save Files
    save_reports(project_name, stats_df)
    print("\nDone.\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compute test–retest reliability metrics.")
    parser.add_argument(
        "--project",
        required=True,
        help="Project folder name (e.g., project-01_dhl).",
    )
    args = parser.parse_args()
    main(args.project)
