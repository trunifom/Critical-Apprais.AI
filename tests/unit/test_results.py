"""Results table, its export and reading back, the numbers for the charts, and the charts."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any

import pytest
from results_helpers import project_with_run
from typer.testing import CliRunner

from crapai.cli import app
from crapai.errors import ConfigError
from crapai.llm.mock_provider import MockProvider
from crapai.screening.store import RunStore
from crapai.services import screening as svc
from crapai.services.results import (
    compare_runs,
    export_comparison,
    export_results,
    results_table,
    runs_with_results,
)
from crapai.stats import results as stats
from crapai.ui import charts
from crapai.ui.theme import PALETTES, contrast_ratio


def two_runs(tmp_path: Path, scenario: str = "S12") -> tuple[Any, str, str]:
    """A project with two finished runs of the same scenario (so decisions start out identical)."""
    workspace = project_with_run(tmp_path, scenario=scenario)
    run_a = runs_with_results(workspace)[0]
    svc.screen_project(
        workspace, svc.RunOptions(provider=MockProvider(scenario), install_signal_handler=False)
    )
    run_b = next(r for r in runs_with_results(workspace) if r != run_a)
    return workspace, run_a, run_b

# --- outcome and table ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "reason,status,decision,expected",
    [
        ("DUPLICATE", "", "", "PRE_EXCLUDED"),
        ("", "", "", "NOT_SCREENED"),
        ("", "ok", "INCLUDE", "INCLUDE"),
        ("", "ok", "EXCLUDE", "EXCLUDE"),
        ("", "ok", "UNCERTAIN", "UNCERTAIN"),
        ("", "parse_error", "", "ERROR"),
        ("", "ok", "", "ERROR"),
        ("", "ok", "MAYBE", "ERROR"),
    ],
)
def test_the_outcome_category(reason: str, status: str, decision: str, expected: str) -> None:
    assert stats.outcome_of(reason, status, decision) == expected


def test_the_table_has_one_row_per_record_with_the_documented_columns(tmp_path: Path) -> None:
    workspace = project_with_run(tmp_path)
    run_id, rows = results_table(workspace)
    assert run_id in runs_with_results(workspace) and len(rows) == 24
    assert set(rows[0]) == set(stats.RESULT_COLUMNS)
    counts = {o: sum(1 for r in rows if r["outcome"] == o) for o in stats.OUTCOMES}
    assert counts["PRE_EXCLUDED"] == 4 and counts["NOT_SCREENED"] == 0  # records without abstract
    assert counts["EXCLUDE"] > 0 and counts["UNCERTAIN"] > 0 and counts["INCLUDE"] > 0
    sent = [r for r in rows if r["outcome"] != "PRE_EXCLUDED"]
    assert all(r["run_id"] == run_id and r["batch"] and r["tokens_in"] > 0 for r in sent)
    assert all(r["abstract_words"] == 0 for r in rows if r["outcome"] == "PRE_EXCLUDED")


def test_no_run_or_an_unknown_run_is_a_clear_error(tmp_path: Path) -> None:
    workspace = project_with_run(tmp_path, with_run=False)
    with pytest.raises(ConfigError) as info:
        results_table(workspace)
    assert info.value.code == "E203"
    workspace = project_with_run(tmp_path / "b")
    with pytest.raises(ConfigError):
        results_table(workspace, "nope")


# --- export and reading back ----------------------------------------------------------------------


def test_csv_export_can_be_read_back_to_the_same_numbers(tmp_path: Path) -> None:
    workspace = project_with_run(tmp_path)
    _run, rows = results_table(workspace)
    summary = export_results(workspace, "csv", delimiter=";")
    assert (
        summary.what == "results"
        and summary.records == 24
        and summary.path.parent.name == "exports"
    )
    back = stats.read_table_file(summary.path.name, summary.path.read_bytes())
    assert [r["outcome"] for r in back] == [r["outcome"] for r in rows]
    assert stats.analyse(back).by_outcome == stats.analyse(rows).by_outcome


def test_xlsx_export_can_be_read_back(tmp_path: Path) -> None:
    pytest.importorskip("openpyxl")
    workspace = project_with_run(tmp_path)
    summary = export_results(workspace, "xlsx")
    back = stats.read_table_file(summary.path.name, summary.path.read_bytes())
    assert len(back) == 24 and {r["outcome"] for r in back} <= set(stats.OUTCOMES)


def test_a_formula_in_a_title_is_protected_in_the_export(tmp_path: Path) -> None:
    workspace = project_with_run(tmp_path, 3)
    text = export_results(workspace, "csv").path.read_text(encoding="utf-8-sig")
    assert not any(line.startswith("=") for line in text.splitlines())


def test_unknown_format_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        export_results(project_with_run(tmp_path, 3), "ris")


def test_the_command_line_exports_the_results(tmp_path: Path) -> None:
    workspace = project_with_run(tmp_path)
    result = CliRunner().invoke(
        app, ["export", str(workspace.root), "--what", "results", "--format", "csv", "--lang", "en"]
    )
    assert result.exit_code == 0, result.output
    assert any((workspace.root / "exports").glob("results-*.csv"))
    bad = CliRunner().invoke(app, ["export", str(workspace.root), "--what", "nothing"])
    assert bad.exit_code == 1


# --- reading files that are not ours ---------------------------------------------------------------


def csv_bytes(rows: list[dict[str, Any]], delimiter: str = ",") -> bytes:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0]), delimiter=delimiter)
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8-sig")


def test_a_minimal_table_with_only_a_decision_column_is_accepted() -> None:
    data = csv_bytes([{"title": "A", "decision": "include"}, {"title": "B", "decision": "EXCLUDE"}])
    rows = stats.read_table_file("mine.csv", data)
    assert [r["outcome"] for r in rows] == ["INCLUDE", "EXCLUDE"]


@pytest.mark.parametrize("delimiter", [",", ";", "\t"])
def test_delimiters_are_detected(delimiter: str) -> None:
    rows = stats.read_table_file(
        "x.csv", csv_bytes([{"outcome": "INCLUDE", "year": "2020"}] * 2, delimiter)
    )
    assert len(rows) == 2 and rows[0]["year"] == 2020


def test_windows_text_encoding_is_read() -> None:
    raw = "title;outcome\nÄrzte und Ärztinnen;INCLUDE\n".encode("cp1252")
    assert stats.read_table_file("x.csv", raw)[0]["title"] == "Ärzte und Ärztinnen"


@pytest.mark.parametrize(
    "name,data",
    [
        ("x.csv", b""),
        ("x.csv", b"title,year\nA,2020\n"),
        ("x.csv", b"outcome\nMAYBE\n"),
        ("x.pdf", b"%PDF"),
        ("x.xlsx", b"not a workbook"),
    ],
)
def test_files_that_are_not_results_tables_are_refused_with_e203(name: str, data: bytes) -> None:
    with pytest.raises(ConfigError) as info:
        stats.read_table_file(name, data)
    assert info.value.code == "E203"


def test_numbers_in_odd_notation_are_read() -> None:
    row = stats.read_table_file(
        "x.csv",
        csv_bytes([{"outcome": "INCLUDE", "year": "2'020", "cost": "0,25", "consistent": "ja"}]),
    )[0]
    assert row["year"] == 2020 and row["cost"] == 0.25 and row["consistent"] is True


# --- numbers for the charts -------------------------------------------------------------------------


def test_the_analysis_adds_up(tmp_path: Path) -> None:
    _run, rows = results_table(project_with_run(tmp_path))
    a = stats.analyse(rows)
    assert (
        a.total == 24
        and sum(a.by_outcome.values()) == 24
        and set(a.by_outcome) == set(stats.OUTCOMES)
    )
    assert (
        a.screened == a.by_outcome["INCLUDE"] + a.by_outcome["EXCLUDE"] + a.by_outcome["UNCERTAIN"]
    )
    assert sum(sum(v.values()) for v in a.by_source.values()) == 24 and list(a.by_source) == [
        "PubMed"
    ]
    assert sum(sum(v.values()) for v in a.by_year.values()) == 24
    assert sum(b["count"] for b in a.word_bins) == sum(
        1 for r in rows if r["outcome"] != "PRE_EXCLUDED"
    )
    assert a.status_counts == {"ok": 20} and a.reason_counts == {"NO_ABSTRACT": 4}
    assert a.tokens_in > 0 and sum(b["tokens_in"] for b in a.batches) == a.tokens_in
    assert len(a.uncertain) == a.by_outcome["UNCERTAIN"]
    assert a.consistency["consistent"] + a.consistency.get("inconsistent", 0) == a.screened


def test_an_empty_table_and_one_without_optional_columns_do_not_break_the_analysis() -> None:
    assert stats.analyse([]).total == 0
    a = stats.analyse([{"outcome": "INCLUDE"}, {"outcome": "EXCLUDE"}])
    assert a.by_outcome["INCLUDE"] == 1 and a.batches == [] and a.cost is None


def test_the_scatter_sample_is_limited() -> None:
    rows = [
        {"outcome": "INCLUDE", "year": 2000 + i % 20, "abstract_words": 100 + i}
        for i in range(9000)
    ]
    assert len(stats.analyse(rows).points) <= stats.MAX_POINTS + 1


# --- charts --------------------------------------------------------------------------------------------

LABEL = {"INCLUDE": "Yes", "EXCLUDE": "No", "UNCERTAIN": "Maybe"}.get


def label(name: str) -> str:
    return LABEL(name, name)


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_every_outcome_colour_is_visible_against_the_background(theme: str) -> None:
    background = PALETTES[theme]["bg"]
    for outcome, colour in charts.CHART_COLORS[theme].items():
        assert contrast_ratio(colour, background) >= 1.9, (
            theme,
            outcome,
        )  # the faint grey is a "not yet"
    strong = ("INCLUDE", "EXCLUDE", "UNCERTAIN")
    assert all(contrast_ratio(charts.CHART_COLORS[theme][o], background) >= 3.0 for o in strong)


def test_the_colours_of_the_outcomes_differ() -> None:
    for theme in ("light", "dark"):
        assert len(set(charts.CHART_COLORS[theme].values())) == len(stats.OUTCOMES)


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_chart_text_follows_the_palette(theme: str) -> None:
    cfg = charts.config(theme)
    assert cfg["axis"]["labelColor"] == PALETTES[theme]["text"]
    assert cfg["legend"]["labelColor"] == PALETTES[theme]["text"] and cfg["background"] is None


def test_the_donut_uses_translated_names_and_leaves_out_empty_categories() -> None:
    spec = charts.donut({"INCLUDE": 3, "EXCLUDE": 0, "UNCERTAIN": 1}, "dark", label)
    values = spec["data"]["values"]
    assert [v["label"] for v in values] == ["Yes", "Maybe"]
    assert spec["encoding"]["color"]["scale"]["domain"] == ["Yes", "Maybe"]
    assert spec["encoding"]["color"]["scale"]["range"] == [
        charts.CHART_COLORS["dark"]["INCLUDE"], charts.CHART_COLORS["dark"]["UNCERTAIN"],
    ]  # fmt: skip


def test_bars_are_sorted_and_stacked_bars_can_show_shares() -> None:
    spec = charts.bars([("a", 1), ("b", 5)], "light", x_title="x", y_title="y")
    assert [v["category"] for v in spec["data"]["values"]] == ["b", "a"]
    table = {"PubMed": {"INCLUDE": 2, "EXCLUDE": 1}, "Embase": {"INCLUDE": 4}}
    shares = charts.stacked(
        table, "light", label, category_title="s", count_title="n", normalise=True
    )
    assert "normalize" in (
        shares["encoding"]["x"].get("stack"),
        shares["encoding"]["y"].get("stack"),
    )
    years = charts.stacked(
        {2020: {"INCLUDE": 1}},
        "light",
        label,
        category_title="y",
        count_title="n",
        numeric_axis=True,
    )
    assert years["encoding"]["x"]["sort"] == "ascending"


def test_histogram_scatter_and_boxplot_specs() -> None:
    bins = [{"bin_start": 0, "bin_end": 50, "outcome": "INCLUDE", "count": 3}]
    hist = charts.histogram(bins, "dark", label, x_title="w", y_title="n")
    assert (
        hist["encoding"]["x2"] == {"field": "bin_end"}
        and hist["data"]["values"][0]["label"] == "Yes"
    )
    points = [
        {"outcome": "EXCLUDE", "words": 120, "year": 2020},
        {"outcome": "EXCLUDE", "words": 90, "year": None},
    ]
    assert (
        len(charts.scatter(points, "light", label, x_title="y", y_title="w")["data"]["values"]) == 1
    )
    assert charts.boxplot(points, "light", label, y_title="w")["mark"]["type"] == "boxplot"


def test_specs_are_plain_json() -> None:
    import json

    json.dumps(charts.donut({"INCLUDE": 1}, "light", label))
    json.dumps(charts.histogram([], "light", label, x_title="a", y_title="b"))


# --- comparing several runs (plan chapter 14.1) ---------------------------------------------------


def test_compare_runs_needs_at_least_two_run_ids(tmp_path: Path) -> None:
    workspace = project_with_run(tmp_path)
    run_id = runs_with_results(workspace)[0]
    with pytest.raises(ConfigError) as info:
        compare_runs(workspace, [run_id])
    assert info.value.code == "E203"


def test_compare_runs_rejects_an_unknown_run(tmp_path: Path) -> None:
    workspace, run_a, _run_b = two_runs(tmp_path)
    with pytest.raises(ConfigError):
        compare_runs(workspace, [run_a, "nope"])


def test_compare_runs_rejects_the_same_run_id_twice(tmp_path: Path) -> None:
    workspace, run_a, _run_b = two_runs(tmp_path)
    with pytest.raises(ConfigError) as info:
        compare_runs(workspace, [run_a, run_a])
    assert info.value.code == "E203"


def test_identical_runs_agree_completely(tmp_path: Path) -> None:
    workspace, run_a, run_b = two_runs(tmp_path)
    rows, summary = compare_runs(workspace, [run_a, run_b])
    assert len(rows) == 24 and summary.n_common > 0
    assert all(p.agreement == 1.0 and p.kappa == pytest.approx(1.0) for p in summary.pairwise)
    assert summary.fleiss_kappa == pytest.approx(1.0) and summary.unstable == []
    assert all(row["agreement"] in ("", "unanimous") for row in rows)
    assert any(row["agreement"] == "unanimous" for row in rows)


def test_a_disagreement_is_flagged_split_and_unstable(tmp_path: Path) -> None:
    workspace, run_a, run_b = two_runs(tmp_path)
    store_b = RunStore(workspace.runs_dir / run_b)
    uid, decided = next(
        (u, r) for u, r in store_b.last_results().items() if r.status == "ok" and r.decision
    )
    flipped = "EXCLUDE" if decided.decision != "EXCLUDE" else "INCLUDE"
    store_b.append_result(decided.model_copy(update={"decision": flipped}))
    rows, summary = compare_runs(workspace, [run_a, run_b])
    changed = next(r for r in rows if r["study_uid"] == uid)
    assert changed["agreement"] == "split"
    assert {u.study_uid for u in summary.unstable} == {uid}
    assert summary.fleiss_kappa is not None and summary.fleiss_kappa < 1.0


def test_export_comparison_writes_one_column_group_per_run(tmp_path: Path) -> None:
    workspace, run_a, run_b = two_runs(tmp_path)
    summary = export_comparison(workspace, [run_a, run_b], "csv")
    assert summary.what == "compare" and summary.records == 24
    header = summary.path.read_text(encoding="utf-8-sig").splitlines()[0]
    assert f"decision__{run_a}" in header and f"decision__{run_b}" in header and "agreement" in header


def test_export_comparison_rejects_an_unknown_format(tmp_path: Path) -> None:
    workspace, run_a, run_b = two_runs(tmp_path)
    with pytest.raises(ConfigError):
        export_comparison(workspace, [run_a, run_b], "ris")


def test_the_command_line_compares_runs_and_writes_a_file(tmp_path: Path) -> None:
    workspace, run_a, run_b = two_runs(tmp_path)
    result = CliRunner().invoke(
        app,
        ["compare-runs", str(workspace.root), "--runs", f"{run_a},{run_b}", "--lang", "en"],
    )
    assert result.exit_code == 0, result.output
    assert "kappa" in result.output.lower()
    assert any((workspace.root / "exports").glob("compare-*.csv"))


def test_the_command_line_as_json(tmp_path: Path) -> None:
    workspace, run_a, run_b = two_runs(tmp_path)
    result = CliRunner().invoke(
        app, ["compare-runs", str(workspace.root), "--runs", f"{run_a},{run_b}", "--json"]
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert data["run_ids"] == [run_a, run_b]
    assert "fleiss_kappa" in data and "pairwise" in data and len(data["pairwise"]) == 1


def test_the_command_line_refuses_a_single_run(tmp_path: Path) -> None:
    workspace = project_with_run(tmp_path)
    run_id = runs_with_results(workspace)[0]
    result = CliRunner().invoke(app, ["compare-runs", str(workspace.root), "--runs", run_id])
    assert result.exit_code == 1
