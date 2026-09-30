"""Readers and statistics for result files written by SARA-App (legacy format).

Legacy run files are ``;``-separated CSV files named ``<YYYYMMDD-HHMM>_<project-uuid>_run-NN.csv``
with (among others) the columns ``study_uid`` and ``label`` (0 = exclude, 1 = include/uncertain).
Encodings vary between UTF-8 and Windows-1252, therefore a fallback chain is used.

This module exists so that (a) old runs stay analysable and (b) the golden reports in
``tests/expected/`` can be reproduced by the new code base without scikit-learn.
"""

from __future__ import annotations

import logging
import re
from itertools import combinations
from pathlib import Path

import pandas as pd

LOGGER = logging.getLogger(__name__)

ID_COL = "study_uid"
LABEL_COL = "label"
RUN_FILE_GLOB = "*_run-*.csv"
ENCODINGS: tuple[str, ...] = ("utf-8-sig", "utf-8", "cp1252", "latin-1")


def read_legacy_run(path: Path, columns: tuple[str, ...] = (ID_COL, LABEL_COL)) -> pd.DataFrame:
    """Read the requested ``columns`` of one legacy run CSV.

    Tries the encodings in ``ENCODINGS`` in order and returns the first successful read.

    Raises:
        ValueError: if no encoding yields a table that contains all requested columns.
    """
    last_error: Exception | None = None
    for encoding in ENCODINGS:
        try:
            frame = pd.read_csv(path, sep=";", encoding=encoding, dtype=str, keep_default_na=False)
        except UnicodeDecodeError as exc:
            last_error = exc
            continue
        missing = [c for c in columns if c not in frame.columns]
        if missing:
            last_error = ValueError(f"columns {missing} missing when read as {encoding}")
            continue
        return frame.loc[:, list(columns)].copy()
    raise ValueError(f"Cannot read {path.name}: tried {ENCODINGS}; last error: {last_error}")


def run_tag(path: Path) -> str:
    """Return the run tag (``run-01``) from a legacy file name."""
    match = re.search(r"(run-\d+)", path.stem)
    if not match:
        raise ValueError(f"No run tag in file name: {path.name}")
    return match.group(1)


def load_runs(project_dir: Path) -> pd.DataFrame:
    """Merge the ``label`` of all runs in ``project_dir`` on ``study_uid`` (outer join).

    Returns a frame with ``study_uid`` and one column per run (``run-01`` ...). Labels are numeric;
    empty labels become ``NaN``.
    """
    files = sorted(project_dir.glob(RUN_FILE_GLOB))
    if not files:
        raise FileNotFoundError(f"No files matching {RUN_FILE_GLOB!r} in {project_dir}")
    merged: pd.DataFrame | None = None
    for path in files:
        frame = read_legacy_run(path)
        frame[LABEL_COL] = pd.to_numeric(frame[LABEL_COL], errors="coerce")
        frame = frame.rename(columns={LABEL_COL: run_tag(path)})
        merged = frame if merged is None else merged.merge(frame, on=ID_COL, how="outer")
    assert merged is not None
    return merged


def cohen_kappa(first: pd.Series, second: pd.Series) -> float:
    """Cohen's kappa for two equally long label series (unweighted).

    Returns ``nan`` when the expected agreement is 1 (both raters use a single identical class),
    where kappa is undefined (scikit-learn behaves the same).
    """
    if len(first) != len(second) or len(first) == 0:
        raise ValueError("Series must be non-empty and of equal length")
    labels = sorted(set(first) | set(second))
    n = len(first)
    observed = float((first.to_numpy() == second.to_numpy()).mean())
    expected = sum(
        (float((first == lab).sum()) / n) * (float((second == lab).sum()) / n) for lab in labels
    )
    if expected == 1.0:
        return float("nan")
    return (observed - expected) / (1.0 - expected)


def interpret_kappa(kappa: float) -> str:
    """Landis & Koch (1977) verbal interpretation, as used in SARA-App reports."""
    if kappa != kappa:  # NaN
        return "Undefined"
    if kappa < 0:
        return "Poor"
    for upper, name in (
        (0.20, "Slight"),
        (0.40, "Fair"),
        (0.60, "Moderate"),
        (0.80, "Substantial"),
        (1.0, "Almost Perfect"),
    ):
        if kappa <= upper:
            return name
    return "Unknown"


def pairwise_stats(runs: pd.DataFrame) -> pd.DataFrame:
    """Pairwise agreement statistics for all run columns (same columns as SARA-App reports)."""
    run_cols = [c for c in runs.columns if c.startswith("run-")]
    if len(run_cols) < 2:
        raise ValueError("At least two runs are required")
    rows = []
    for run_a, run_b in combinations(run_cols, 2):
        subset = runs[[run_a, run_b]].dropna()
        if subset.empty:
            LOGGER.warning("No overlapping records between %s and %s", run_a, run_b)
            continue
        agreement = float((subset[run_a] == subset[run_b]).mean())
        kappa = cohen_kappa(subset[run_a], subset[run_b])
        rows.append(
            {
                "run1": run_a,
                "run2": run_b,
                "n_overlap": len(subset),
                "percent_agreement": round(agreement, 4),
                "cohen_kappa": round(kappa, 4),
                "interpretation": interpret_kappa(kappa),
            }
        )
    return pd.DataFrame(rows)
