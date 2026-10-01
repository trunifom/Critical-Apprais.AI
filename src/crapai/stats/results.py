"""The results table of a screening run, and the numbers behind the charts.

A *results table* has one row per record of the project and says what became of it: sent to the
model and decided (``INCLUDE``, ``EXCLUDE``, ``UNCERTAIN``), sent but failed (``ERROR``), held back
before the model (``PRE_EXCLUDED``: duplicate, language filter, no abstract ...) or not screened
yet (``NOT_SCREENED``). It is what ``crapai export --what results`` writes, and what the
"Evaluation" page can read back from a file, so an exported table can be analysed later, on
another computer, or after the project folder is gone.

This module is pure: it builds, reads, checks and summarises tables made of plain dictionaries. It
reads no project and imports no interface code (the service :mod:`crapai.services.results` does
the file work).
"""

from __future__ import annotations

import csv
import io
import json
import math
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from crapai.errors import ConfigError

OUTCOMES: tuple[str, ...] = (
    "INCLUDE",
    "EXCLUDE",
    "UNCERTAIN",
    "ERROR",
    "PRE_EXCLUDED",
    "NOT_SCREENED",
)
DECISIONS = ("INCLUDE", "EXCLUDE", "UNCERTAIN")
RESULT_COLUMNS: tuple[str, ...] = (
    "study_uid", "title", "year", "journal", "doi", "source_label", "abstract_words",
    "exclusion_reason", "outcome", "decision", "derived_decision", "consistent", "status",
    "error_code", "reasoning", "flags", "quote_unverified", "model_returned", "run_id", "batch",
    "tokens_in", "tokens_out", "cost", "latency_s",
)  # fmt: skip
MAX_POINTS = 2000  # scatter points sent to the browser
MAX_LISTED = 200  # rows of the "uncertain" list
_INT = ("year", "abstract_words", "batch", "tokens_in", "tokens_out", "quote_unverified")
_FLOAT = ("cost", "latency_s")


def outcome_of(exclusion_reason: str, status: str, decision: str) -> str:
    """The outcome category of one record.

    Args:
        exclusion_reason: The reason in ``records.csv`` (``""`` if the record goes to the model).
        status: Result status of the run (``ok``, ``parse_error`` ...) or ``""`` if none.
        decision: ``INCLUDE``, ``EXCLUDE``, ``UNCERTAIN`` or ``""``.
    """
    if exclusion_reason:
        return "PRE_EXCLUDED"
    if not status:
        return "NOT_SCREENED"
    if status != "ok" or decision not in DECISIONS:
        return "ERROR"
    return decision


def build_table(
    records: Iterable[Any], results: Mapping[str, Any], run_id: str = ""
) -> list[dict[str, Any]]:
    """Join the records of a project with the last result per record of one run.

    Args:
        records: ``Record`` objects (``crapai.io.records_store``).
        results: ``study_uid`` to ``ResultRow`` (``RunStore.last_results()``).
        run_id: The run the results come from.
    """
    rows: list[dict[str, Any]] = []
    for record in records:
        result = results.get(record.study_uid)
        status = result.status if result else ""
        decision = result.decision if result else ""
        rows.append(
            {
                "study_uid": record.study_uid,
                "title": record.title,
                "year": record.year,
                "journal": record.journal,
                "doi": record.doi,
                "source_label": record.source_label,
                "abstract_words": len(record.abstract.split()),
                "exclusion_reason": record.exclusion_reason,
                "outcome": outcome_of(record.exclusion_reason, status, decision),
                "decision": decision,
                "derived_decision": result.derived_decision if result else "",
                "consistent": result.consistent if result else None,
                "status": status,
                "error_code": result.error_code if result else "",
                "reasoning": result.reasoning if result else "",
                "flags": "; ".join(result.flags) if result else "",
                "quote_unverified": len(result.quote_unverified) if result else 0,
                "model_returned": result.model_returned if result else "",
                "run_id": run_id if result else "",
                "batch": (result.batch + 1) if result else None,
                "tokens_in": result.tokens_in if result else 0,
                "tokens_out": result.tokens_out if result else 0,
                "cost": result.cost if result else None,
                "latency_s": result.latency_s if result else None,
            }
        )
    return rows


COMPARE_BASE_COLUMNS: tuple[str, ...] = (
    "study_uid", "title", "year", "journal", "exclusion_reason",
)  # fmt: skip
COMPARE_RUN_FIELDS: tuple[str, ...] = ("status", "decision", "reasoning", "model_returned")


def compare_columns(run_ids: Sequence[str]) -> tuple[str, ...]:
    """Column names of :func:`compare_table` for the given runs, in file order."""
    per_run = tuple(f"{field}__{run_id}" for run_id in run_ids for field in COMPARE_RUN_FIELDS)
    return (*COMPARE_BASE_COLUMNS, *per_run, "agreement")


def compare_table(
    records: Iterable[Any], results_by_run: Mapping[str, Mapping[str, Any]], run_ids: Sequence[str]
) -> list[dict[str, Any]]:
    """One row per record of the project, with one group of columns per run.

    Args:
        records: ``Record`` objects (``crapai.io.records_store``).
        results_by_run: ``run_id`` to ``RunStore.last_results()`` of that run.
        run_ids: The runs to compare, and their column order.

    The ``agreement`` column is ``""`` if fewer than two runs decided the record yet, ``"partial"``
    if some but not all of ``run_ids`` decided it, ``"unanimous"`` if every run that decided it
    chose the same decision, ``"split"`` otherwise.
    """
    rows: list[dict[str, Any]] = []
    for record in records:
        row: dict[str, Any] = {name: getattr(record, name) for name in COMPARE_BASE_COLUMNS}
        decisions: list[str] = []
        for run_id in run_ids:
            result = results_by_run.get(run_id, {}).get(record.study_uid)
            row[f"status__{run_id}"] = result.status if result else ""
            row[f"decision__{run_id}"] = result.decision if result else ""
            row[f"reasoning__{run_id}"] = result.reasoning if result else ""
            row[f"model_returned__{run_id}"] = result.model_returned if result else ""
            if result and result.status == "ok" and result.decision in DECISIONS:
                decisions.append(result.decision)
        if len(decisions) < 2:
            row["agreement"] = ""
        elif len(decisions) < len(run_ids):
            row["agreement"] = "partial"
        elif len(set(decisions)) == 1:
            row["agreement"] = "unanimous"
        else:
            row["agreement"] = "split"
        rows.append(row)
    return rows


def _number(value: Any, convert: type) -> Any:
    if value is None:
        return None
    text = str(value).strip().replace("'", "")
    if not text or text.lower() in ("none", "nan", "null"):
        return None
    try:
        return (
            convert(float(text.replace(",", ".")))
            if convert is int
            else float(text.replace(",", "."))
        )
    except ValueError:
        return None


def _boolean(value: Any) -> bool | None:
    text = str(value).strip().lower()
    if text in ("true", "1", "yes", "ja", "wahr"):
        return True
    if text in ("false", "0", "no", "nein", "falsch"):
        return False
    return None


def normalise_rows(raw: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Check a table read from a file and give its cells proper types.

    A table is usable if it has an ``outcome`` column, or a ``decision`` column from which the
    outcome can be derived. Columns that are missing are left empty; unknown columns are kept.

    Raises:
        ConfigError: E203 if the table is empty, has neither column, or contains an unknown
            outcome value.
    """
    if not raw:
        raise ConfigError(
            "The file has no rows",
            code="E203",
            hint="Export the results again ('crapai export --what results' or the Export page).",
        )
    header = set(raw[0])
    if "outcome" not in header and "decision" not in header:
        raise ConfigError(
            "This is not a results table: it has neither an 'outcome' nor a 'decision' column",
            code="E203",
            hint="Use a file written by 'Export - Screening results' (columns: "
            + ", ".join(RESULT_COLUMNS[:12])
            + ", ...).",
            details={"columns": sorted(header)[:30]},
        )
    rows: list[dict[str, Any]] = []
    for number, source in enumerate(raw, start=2):  # row 1 is the header
        row: dict[str, Any] = {
            name: ("" if source.get(name) is None else source[name]) for name in source
        }
        for name in _INT:
            row[name] = _number(row.get(name), int)
        for name in _FLOAT:
            row[name] = _number(row.get(name), float)
        row["consistent"] = _boolean(row.get("consistent", ""))
        for name in ("title", "source_label", "exclusion_reason", "decision", "status", "flags"):
            row[name] = str(row.get(name, "") or "").strip()
        outcome = str(row.get("outcome", "") or "").strip().upper()
        if not outcome:
            outcome = outcome_of(
                row["exclusion_reason"], row["status"] or "ok", row["decision"].upper()
            )
        if outcome not in OUTCOMES:
            raise ConfigError(
                f"Row {number}: unknown outcome '{outcome}'",
                code="E203",
                hint="Valid values: " + ", ".join(OUTCOMES),
            )
        row["outcome"] = outcome
        rows.append(row)
    return rows


def read_table_file(name: str, data: bytes) -> list[dict[str, Any]]:
    """Read a results table from the bytes of a CSV or XLSX file and check it.

    Raises:
        ConfigError: E203 for another file type, an unreadable file, XLSX without ``openpyxl``,
            or a table that :func:`normalise_rows` refuses.
    """
    lower = name.lower()
    if lower.endswith(".xlsx"):
        return normalise_rows(_read_xlsx(data))
    if lower.endswith((".csv", ".tsv", ".txt")):
        return normalise_rows(_read_csv(data))
    raise ConfigError(
        f"Unsupported file type: {name}",
        code="E203",
        hint="Use the CSV or XLSX file written by the results export.",
    )


def _read_csv(data: bytes) -> list[dict[str, str]]:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:  # pragma: no cover - cp1252 decodes almost everything
        raise ConfigError("The file is not readable text", code="E103")
    first = text.splitlines()[0] if text.strip() else ""
    delimiter = max(",;\t", key=first.count) if first else ","
    return list(csv.DictReader(io.StringIO(text), delimiter=delimiter))


def _read_xlsx(data: bytes) -> list[dict[str, Any]]:
    try:
        import openpyxl
    except ImportError as exc:
        raise ConfigError(
            "Reading Excel files needs the package openpyxl",
            code="E203",
            hint='Install it with: pip install "crapai[xlsx]" or upload the CSV file instead.',
        ) from exc
    try:
        book = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        sheet = book.worksheets[0]
        lines = list(sheet.iter_rows(values_only=True))
    except Exception as exc:  # noqa: BLE001 - any broken workbook is the same message
        raise ConfigError("The Excel file cannot be read", code="E203") from exc
    if not lines:
        return []
    header = [str(cell).strip() if cell is not None else "" for cell in lines[0]]
    return [
        dict(zip(header, row, strict=False)) for row in lines[1:] if any(c is not None for c in row)
    ]


def _bin_width(maximum: int, bins: int = 25) -> int:
    return max(10, int(math.ceil(maximum / bins / 10.0)) * 10)


@dataclass
class Analysis:
    """Aggregated numbers for the charts of the Evaluation page.

    Attributes:
        total: Rows of the table.
        by_outcome: Rows per outcome category (all categories present, possibly 0).
        screened: Rows decided by the model (include, exclude, uncertain).
        by_source: Per source label, rows per outcome.
        by_year: Per publication year, rows per outcome.
        status_counts: Result status per row that was sent (``ok``, ``parse_error`` ...).
        flag_counts: How often each flag occurs (``inconsistent``, ``quote_unverified`` ...).
        reason_counts: Records held back before the model, per reason.
        consistency: ``consistent`` / ``inconsistent`` counts among decided rows.
        word_bins: Histogram of abstract length: ``bin_start``, ``bin_end``, ``outcome``, ``count``.
        points: Sample of ``{outcome, words, year}`` for the scatter plot and box plot.
        batches: Tokens and cost per batch.
        latency_bins: Histogram of the answer time in seconds.
        uncertain: The first rows with outcome ``UNCERTAIN``.
        tokens_in, tokens_out, cost: Totals (``cost`` is None if no row has a cost).
    """

    total: int = 0
    by_outcome: dict[str, int] = field(default_factory=dict)
    screened: int = 0
    by_source: dict[str, dict[str, int]] = field(default_factory=dict)
    by_year: dict[int, dict[str, int]] = field(default_factory=dict)
    status_counts: dict[str, int] = field(default_factory=dict)
    flag_counts: dict[str, int] = field(default_factory=dict)
    reason_counts: dict[str, int] = field(default_factory=dict)
    consistency: dict[str, int] = field(default_factory=dict)
    word_bins: list[dict[str, Any]] = field(default_factory=list)
    points: list[dict[str, Any]] = field(default_factory=list)
    batches: list[dict[str, Any]] = field(default_factory=list)
    latency_bins: list[dict[str, Any]] = field(default_factory=list)
    uncertain: list[dict[str, Any]] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    cost: float | None = None


def analyse(rows: Sequence[Mapping[str, Any]]) -> Analysis:
    """Summarise a (normalised) results table for the charts. Reads rows once; no sampling bias:
    the scatter sample takes every n-th row."""
    result = Analysis(total=len(rows))
    outcomes = Counter(str(r.get("outcome", "NOT_SCREENED")) for r in rows)
    result.by_outcome = {name: outcomes.get(name, 0) for name in OUTCOMES}
    result.screened = sum(outcomes.get(name, 0) for name in DECISIONS)
    by_source: dict[str, Counter[str]] = {}
    by_year: dict[int, Counter[str]] = {}
    status: Counter[str] = Counter()
    flags: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    consistency: Counter[str] = Counter()
    word_counts: dict[tuple[int, str], int] = {}
    latency: dict[tuple[int, str], int] = {}
    batches: dict[int, list[float]] = {}
    cost_seen = False
    maximum_words = max((int(r.get("abstract_words") or 0) for r in rows), default=0)
    width = _bin_width(maximum_words)
    latencies = [float(r["latency_s"]) for r in rows if r.get("latency_s") not in (None, "")]
    lat_width = max(0.5, round(max(latencies, default=1.0) / 20, 1)) if latencies else 1.0
    stride = max(1, -(-len(rows) // MAX_POINTS))
    for index, row in enumerate(rows):
        outcome = str(row.get("outcome", "NOT_SCREENED"))
        by_source.setdefault(str(row.get("source_label") or "-"), Counter())[outcome] += 1
        year = row.get("year")
        if isinstance(year, int) and 1000 < year < 3000:
            by_year.setdefault(year, Counter())[outcome] += 1
        if row.get("status"):
            status[str(row["status"])] += 1
        for flag in str(row.get("flags") or "").split(";"):
            if flag.strip():
                flags[flag.strip()] += 1
        if row.get("exclusion_reason"):
            reasons[str(row["exclusion_reason"])] += 1
        if outcome in DECISIONS and row.get("consistent") is not None:
            consistency["consistent" if row["consistent"] else "inconsistent"] += 1
        words = int(row.get("abstract_words") or 0)
        if outcome != "PRE_EXCLUDED" or words:
            key = (words // width * width, outcome)
            word_counts[key] = word_counts.get(key, 0) + 1
        if index % stride == 0 and words:
            result.points.append({"outcome": outcome, "words": words, "year": year})
        value = row.get("latency_s")
        if value not in (None, ""):
            bin_key = (int(float(value) // lat_width), outcome)
            latency[bin_key] = latency.get(bin_key, 0) + 1
        result.tokens_in += int(row.get("tokens_in") or 0)
        result.tokens_out += int(row.get("tokens_out") or 0)
        if row.get("cost") not in (None, ""):
            cost_seen = True
            result.cost = (result.cost or 0.0) + float(row["cost"])
        if row.get("batch") not in (None, ""):
            entry = batches.setdefault(int(row["batch"]), [0.0, 0.0, 0.0])
            entry[0] += int(row.get("tokens_in") or 0)
            entry[1] += int(row.get("tokens_out") or 0)
            entry[2] += float(row.get("cost") or 0.0)
        if outcome == "UNCERTAIN" and len(result.uncertain) < MAX_LISTED:
            result.uncertain.append(dict(row))
    result.by_source = {k: dict(v) for k, v in sorted(by_source.items())}
    result.by_year = {k: dict(v) for k, v in sorted(by_year.items())}
    result.status_counts = dict(status)
    result.flag_counts = dict(flags)
    result.reason_counts = dict(reasons)
    result.consistency = dict(consistency)
    result.word_bins = [
        {"bin_start": start, "bin_end": start + width, "outcome": outcome, "count": count}
        for (start, outcome), count in sorted(word_counts.items())
    ]
    result.latency_bins = [
        {
            "bin_start": round(b * lat_width, 2),
            "bin_end": round((b + 1) * lat_width, 2),
            "outcome": o,
            "count": c,
        }
        for (b, o), c in sorted(latency.items())
    ]
    result.batches = [
        {"batch": number, "tokens_in": int(v[0]), "tokens_out": int(v[1]), "cost": round(v[2], 6)}
        for number, v in sorted(batches.items())
    ]
    if not cost_seen:
        result.cost = None
    return result


def to_json(analysis: Analysis) -> str:
    """The analysis as JSON text (for tests and for saving a figure's data)."""
    return json.dumps(analysis.__dict__, default=str, ensure_ascii=False)
