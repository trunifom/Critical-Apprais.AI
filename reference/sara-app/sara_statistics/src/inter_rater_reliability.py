"""
Script to measure Inter-rater Reliability between AI and Human results.
Generates a report with contingency table and metrics.

This script compares the classification results of an AI model against a human gold standard.
It performs data loading, filtering, sampling, matching, and statistical analysis.
"""

import logging
import pandas as pd
import numpy as np
from pathlib import Path
from sklearn.metrics import confusion_matrix, accuracy_score, cohen_kappa_score, precision_score, recall_score, f1_score
from datetime import datetime

# Configure logger to display INFO messages to the console
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# ==========================================
# CONFIGURATION
# ==========================================

# --- File Paths ---
# Base directory where the input CSV files are located
BASE_DATA_DIR = Path(r"C:\Users\trug\OneDrive - ZHAW\Sharepoint_SARA_SmartArtificalReviewAssistant\_data\private\systematic reviews\Digital Health Literacy\2025-12-02_FullDataset")

# Filenames for AI and Human results
AI_FILE_NAME = "2025-12-03_1710_e32ec957-f8c6-4ce2-be94-7f47b8cff2b5_run1.csv"
HUMAN_FILE_NAME = "2025-12-27_19-28_Review_Daten_Clean.csv"

# --- Output Settings ---
# Directory where reports (CSV and TXT) will be saved
OUTPUT_DIR = Path("sara_statistics/reports/inter_rater")

# Base name for the output report files (will be prefixed with timestamp)
OUTPUT_FILE_BASE_NAME = "inter-rater_report_summary_project-DigitalHealthLiteracy"

# --- Sampling Settings ---
# Number of random samples to draw from the AI dataset. Set to None to use all available rows.
SAMPLE_SIZE = None
#SAMPLE_SIZE = 1000

# Range of rows to exclude from the sampling pool (e.g., training data).
# Rows from EXCLUDE_RANGE_START up to (but not including) EXCLUDE_RANGE_END will be ignored.
EXCLUDE_RANGE_START = 0     
EXCLUDE_RANGE_END = 10     

# --- Matching Settings ---
# Column names used to match records between the two files (e.g., by Title)
AI_MATCH_COL = "title"
HUMAN_MATCH_COL = "title"

# --- Filtering Settings (AI Data) ---
# Dictionary defining exclusion criteria for the AI dataset.
# Format: "Column Name": "Value to Exclude"
# Rows matching these criteria will be removed before analysis.
AI_FILTERS = {
    "exclusion_reason": "DUPLICATE",
    "abstract": "no abstract"
}

# --- Label Settings (AI) ---
# Column containing the classification label in the AI file
AI_LABEL_COL = "label"
# No mapping needed if AI labels are already 0 (Exclude) and 1 (Include).
# If they are strings, you would need to add a mapping logic similar to the human one.

# --- Label Settings (Human) ---
# Column containing the classification label in the Human file
HUMAN_LABEL_COL = "source_file"

# Mapping rules for Human labels.
# Keys are substrings to look for in the column value.
# Values are the corresponding integer labels (0 for Exclude, 1 for Include).
HUMAN_LABEL_MAPPING = {
    "irrelevant": 0,
    "select": 1
}

# ==========================================

def load_csv_robust(file_path: Path) -> pd.DataFrame:
    """
    Load a CSV file with robust handling for different encodings and separators.
    
    Args:
        file_path (Path): The path to the CSV file.
        
    Returns:
        pd.DataFrame: The loaded pandas DataFrame.
        
    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the file cannot be read with supported encodings/separators.
    """
    if not file_path.exists():
        logger.error(f"File not found: {file_path}")
        raise FileNotFoundError(f"File not found: {file_path}")

    encodings = ['utf-8', 'cp1252', 'latin1']
    separators = [';', ',']
    
    logger.info(f"Attempting to load {file_path.name}...")
    
    for encoding in encodings:
        for sep in separators:
            try:
                df = pd.read_csv(file_path, sep=sep, encoding=encoding)
                # Basic check: if we have only 1 column, it's likely the wrong separator was used
                if len(df.columns) > 1:
                    logger.info(f"Successfully loaded {file_path.name} (Encoding: {encoding}, Separator: '{sep}', Rows: {len(df)})")
                    return df
            except Exception:
                continue
                
    logger.error(f"Failed to read {file_path} with standard encodings/separators.")
    raise ValueError(f"Could not read {file_path} with standard encodings/separators.")

def interpret_kappa(value):
    """
    Interpret Cohen's Kappa based on Landis & Koch (1977).
    """
    if value < 0.00: return "Poor"
    if value <= 0.20: return "Slight"
    if value <= 0.40: return "Fair"
    if value <= 0.60: return "Moderate"
    if value <= 0.80: return "Substantial"
    return "Almost Perfect"

def interpret_score(value):
    """
    General interpretation for Accuracy, Sensitivity, etc.
    """
    if value >= 0.90: return "Excellent"
    if value >= 0.80: return "Good"
    if value >= 0.70: return "Fair"
    return "Poor"

def calculate_metrics(y_true, y_pred):
    """
    Calculate standard classification metrics for binary classification.
    
    Args:
        y_true (array-like): Ground truth (correct) target values.
        y_pred (array-like): Estimated targets as returned by a classifier.
        
    Returns:
        dict: A dictionary containing TP, FP, TN, FN and various scores.
    """
    logger.info("Calculating classification metrics...")
    
    # Force labels to be [0, 1] to ensure confusion matrix shape is correct even if one class is missing in the sample
    tn, fp, fn, tp = confusion_matrix(y_true, y_pred, labels=[0, 1]).ravel()
    
    accuracy = accuracy_score(y_true, y_pred)
    sensitivity = recall_score(y_true, y_pred, pos_label=1, zero_division=0) # True Positive Rate
    specificity = tn / (tn + fp) if (tn + fp) > 0 else 0 # True Negative Rate
    precision = precision_score(y_true, y_pred, pos_label=1, zero_division=0)
    f1 = f1_score(y_true, y_pred, pos_label=1, zero_division=0)
    kappa = cohen_kappa_score(y_true, y_pred)
    
    metrics = {
        "TP": tp, "FP": fp, "TN": tn, "FN": fn,
        "Accuracy": accuracy,
        "Sensitivity (Recall)": sensitivity,
        "Specificity": specificity,
        "Precision": precision,
        "F1 Score": f1,
        "Cohen's Kappa": kappa
    }
    
    logger.info("Metrics calculation complete.")
    return metrics

def main():
    """
    Main execution function.
    """
    logger.info("Starting Inter-rater Reliability Analysis Script")
    
    ai_path = BASE_DATA_DIR / AI_FILE_NAME
    human_path = BASE_DATA_DIR / HUMAN_FILE_NAME
    
    # Create output directory if it doesn't exist
    if not OUTPUT_DIR.exists():
        logger.info(f"Creating output directory: {OUTPUT_DIR}")
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    # --- 1. Load Data ---
    try:
        df_ai = load_csv_robust(ai_path)
        df_human = load_csv_robust(human_path)
    except Exception as e:
        logger.critical(f"Aborting due to file loading error: {e}")
        return
    
    # --- 2. Pre-processing AI Data (Filtering) ---
    logger.info("--- Starting Pre-processing of AI Data ---")
    
    initial_len = len(df_ai)
    
    for col, val in AI_FILTERS.items():
        if col in df_ai.columns:
            # Case-insensitive comparison for string values
            # We filter out rows where the column value matches the exclusion value
            # Using str.lower() for robust comparison
            
            # Count rows to be removed
            mask = df_ai[col].astype(str).str.lower() == str(val).lower()
            remove_count = mask.sum()
            
            if remove_count > 0:
                df_ai = df_ai[~mask]
                logger.info(f"Filtered out {remove_count} rows where '{col}' is '{val}'.")
            else:
                logger.info(f"No rows found with '{col}' equal to '{val}'.")
        else:
            logger.warning(f"Filter column '{col}' not found in AI dataset. Skipping this filter.")

    logger.info(f"AI Data Pre-processing complete. Rows remaining: {len(df_ai)} (Original: {initial_len})")

    # --- 3. Sampling Logic ---
    logger.info("--- Starting Sampling Process ---")
    
    # Create a list of all available indices
    eligible_indices = list(range(len(df_ai)))
    
    # Exclude specific range (e.g., training data)
    if EXCLUDE_RANGE_END > EXCLUDE_RANGE_START:
        exclude_start = max(0, EXCLUDE_RANGE_START)
        exclude_end = min(len(df_ai), EXCLUDE_RANGE_END)
        
        logger.info(f"Excluding rows from index {exclude_start} to {exclude_end} from the sampling pool.")
        
        # Filter out indices that fall within the exclusion range
        eligible_indices = [i for i in eligible_indices if not (exclude_start <= i < exclude_end)]
        logger.info(f"Eligible rows for sampling after exclusion: {len(eligible_indices)}")
        
    # Perform Random Sampling
    if SAMPLE_SIZE and SAMPLE_SIZE < len(eligible_indices):
        logger.info(f"Drawing {SAMPLE_SIZE} random samples from {len(eligible_indices)} eligible rows.")
        sampled_indices = np.random.choice(eligible_indices, size=SAMPLE_SIZE, replace=False)
        df_ai_sampled = df_ai.iloc[sampled_indices].copy()
    else:
        logger.info("Using all eligible rows (SAMPLE_SIZE not set or larger than population).")
        df_ai_sampled = df_ai.iloc[eligible_indices].copy()

    logger.info(f"Sampling complete. Working with {len(df_ai_sampled)} AI records.")

    # --- 4. Matching Records ---
    logger.info("--- Starting Record Matching ---")
    
    # Check if match columns exist
    if AI_MATCH_COL not in df_ai_sampled.columns:
        logger.error(f"Match column '{AI_MATCH_COL}' missing in AI file.")
        return
    if HUMAN_MATCH_COL not in df_human.columns:
        logger.error(f"Match column '{HUMAN_MATCH_COL}' missing in Human file.")
        return

    # Normalize match columns for better matching (lowercase, strip whitespace)
    logger.info(f"Normalizing match columns: AI='{AI_MATCH_COL}', Human='{HUMAN_MATCH_COL}'")
    df_ai_sampled['match_key'] = df_ai_sampled[AI_MATCH_COL].astype(str).str.lower().str.strip()
    df_human['match_key'] = df_human[HUMAN_MATCH_COL].astype(str).str.lower().str.strip()
    
    # Perform Inner Join
    merged = pd.merge(
        df_ai_sampled, 
        df_human, 
        on='match_key', 
        how='inner', 
        suffixes=('_ai', '_human')
    )
    
    logger.info(f"Matching complete. Found {len(merged)} overlapping records between AI sample and Human results.")
    
    if len(merged) == 0:
        logger.error("No matching records found. Please check your match columns and data. Aborting.")
        return

    # --- 5. Label Parsing & Mapping ---
    logger.info("--- Starting Label Parsing & Mapping ---")
    
    # 5.1 AI Label Parsing
    logger.info(f"Parsing AI labels from column '{AI_LABEL_COL}'...")
    
    # Determine the actual column name in the merged dataframe
    # If names collided, pandas adds suffixes. We need to find the right one.
    actual_ai_label_col = AI_LABEL_COL
    if AI_LABEL_COL not in merged.columns and f"{AI_LABEL_COL}_ai" in merged.columns:
        actual_ai_label_col = f"{AI_LABEL_COL}_ai"
    
    if actual_ai_label_col not in merged.columns:
        logger.error(f"AI Label column '{AI_LABEL_COL}' not found in merged data.")
        return

    try:
        merged['y_pred'] = merged[actual_ai_label_col].astype(int)
        logger.info("AI labels successfully converted to integers.")
    except ValueError:
        logger.error(f"Could not convert AI label column '{actual_ai_label_col}' to integers. Check data format.")
        return

    # 5.2 Human Label Parsing
    logger.info(f"Parsing Human labels from column '{HUMAN_LABEL_COL}' using mapping rules...")
    
    actual_human_label_col = HUMAN_LABEL_COL
    if HUMAN_LABEL_COL not in merged.columns and f"{HUMAN_LABEL_COL}_human" in merged.columns:
        actual_human_label_col = f"{HUMAN_LABEL_COL}_human"
        
    if actual_human_label_col not in merged.columns:
        logger.error(f"Human Label column '{HUMAN_LABEL_COL}' not found in merged data.")
        return

    def map_human_val(val):
        """Helper to map string values to 0/1 based on configuration."""
        s = str(val).lower()
        for key, label in HUMAN_LABEL_MAPPING.items():
            if key.lower() in s:
                return label
        return None # Could not map

    merged['y_true'] = merged[actual_human_label_col].apply(map_human_val)
    
    # Drop rows where human label could not be determined
    valid_rows = merged.dropna(subset=['y_true'])
    dropped_count = len(merged) - len(valid_rows)
    
    if dropped_count > 0:
        logger.warning(f"Dropped {dropped_count} rows where human label could not be parsed from '{actual_human_label_col}'.")
    else:
        logger.info("All human labels successfully parsed.")
    
    merged = valid_rows
    merged['y_true'] = merged['y_true'].astype(int)

    if len(merged) == 0:
        logger.error("No valid rows remaining after label parsing. Aborting.")
        return

    # --- 6. Statistical Analysis ---
    logger.info("--- Starting Statistical Analysis ---")
    
    metrics = calculate_metrics(merged['y_true'], merged['y_pred'])
    
    # --- 7. Reporting ---
    logger.info("--- Generating Reports ---")
    
    timestamp = datetime.now().strftime("%Y%m%d-%H%M")
    report_base_name = f"{timestamp}_{OUTPUT_FILE_BASE_NAME}"
    
    # 7.1 CSV Export (Metrics Only)
    csv_out = OUTPUT_DIR / f"{report_base_name}_metrics.csv"
    
    # Create a DataFrame for the metrics
    metrics_df = pd.DataFrame([metrics])
    # Add interpretation columns
    metrics_df['Kappa_Interpretation'] = interpret_kappa(metrics['Cohen\'s Kappa'])
    metrics_df['Accuracy_Interpretation'] = interpret_score(metrics['Accuracy'])
    
    # Reorder columns for better readability
    cols = ['Accuracy', 'Sensitivity (Recall)', 'Specificity', 'Precision', 'F1 Score', 'Cohen\'s Kappa', 
            'TP', 'FP', 'TN', 'FN', 'Kappa_Interpretation', 'Accuracy_Interpretation']
    metrics_df = metrics_df[cols]
    
    metrics_df.to_csv(csv_out, index=False, sep=';')
    logger.info(f"Metrics CSV saved to: {csv_out}")
    
    # 7.2 Text Report
    txt_out = OUTPUT_DIR / f"{report_base_name}.txt"
    
    report_lines = []
    report_lines.append("========================================================")
    report_lines.append("INTER-RATER RELIABILITY REPORT (AI vs HUMAN)")
    report_lines.append(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report_lines.append("========================================================")
    report_lines.append("CONFIGURATION:")
    report_lines.append(f"  AI File:    {AI_FILE_NAME}")
    report_lines.append(f"  Human File: {HUMAN_FILE_NAME}")
    report_lines.append(f"  Sample Size Requested: {SAMPLE_SIZE}")
    report_lines.append(f"  Excluded Range: {EXCLUDE_RANGE_START} - {EXCLUDE_RANGE_END}")
    report_lines.append(f"  AI Filters: {AI_FILTERS}")
    report_lines.append("")
    report_lines.append(f"Final Matched N: {len(merged)}")
    report_lines.append("")
    report_lines.append("CONTINGENCY TABLE (CONFUSION MATRIX)")
    report_lines.append("--------------------------------------------------------")
    report_lines.append(f"{'':<15} | {'Human: Exclude (0)':<20} | {'Human: Include (1)':<20} |")
    report_lines.append("-" * 65)
    report_lines.append(f"{'AI: Exclude (0)':<15} | {metrics['TN']:<20} | {metrics['FN']:<20} |")
    report_lines.append(f"{'AI: Include (1)':<15} | {metrics['FP']:<20} | {metrics['TP']:<20} |")
    report_lines.append("-" * 65)
    report_lines.append("")
    report_lines.append("METRICS")
    report_lines.append("--------------------------------------------------------")
    report_lines.append(f"Accuracy:    {metrics['Accuracy']:.4f} ({interpret_score(metrics['Accuracy'])})")
    report_lines.append(f"Sensitivity: {metrics['Sensitivity (Recall)']:.4f} ({interpret_score(metrics['Sensitivity (Recall)'])} - True Positive Rate)")
    report_lines.append(f"Specificity: {metrics['Specificity']:.4f} ({interpret_score(metrics['Specificity'])} - True Negative Rate)")
    report_lines.append(f"Precision:   {metrics['Precision']:.4f} ({interpret_score(metrics['Precision'])})")
    report_lines.append(f"F1 Score:    {metrics['F1 Score']:.4f} ({interpret_score(metrics['F1 Score'])})")
    kappa_val = metrics["Cohen's Kappa"]
    report_lines.append(f"Kappa:       {kappa_val:.4f} ({interpret_kappa(kappa_val)})")
    report_lines.append("========================================================")
    report_lines.append("INTERPRETATION GUIDE:")
    report_lines.append("  Kappa (Landis & Koch): <0 Poor, 0-0.2 Slight, 0.2-0.4 Fair, 0.4-0.6 Moderate, 0.6-0.8 Substantial, 0.8-1 Almost Perfect")
    report_lines.append("  Other Metrics: >=0.9 Excellent, >=0.8 Good, >=0.7 Fair, <0.7 Poor")
    
    with open(txt_out, "w", encoding="utf-8") as f:
        f.write("\n".join(report_lines))
        
    logger.info(f"Summary report saved to: {txt_out}")
    
    # Print report to console
    print("\n" + "\n".join(report_lines))
    logger.info("Script finished successfully.")

if __name__ == "__main__":
    main()