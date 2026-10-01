"""Chart specifications (Vega-Lite) for the Evaluation page, coloured by the chosen design.

Each function returns a plain dictionary that ``st.vega_lite_chart`` draws, so the charts need no
plotting package and no Streamlit theme: axis text, grid lines, legends and the colour of every
outcome come from :data:`CHART_COLORS` and the palette of :mod:`crapai.ui.theme`, in the light and
in the dark design. The functions import nothing from Streamlit and are tested on their output.

Colour is never the only carrier of meaning: every chart has tooltips and the legend names the
categories in the user's language.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from crapai.stats.results import OUTCOMES
from crapai.ui.theme import PALETTES

#: colour of each outcome per design (checked for distinguishability by eye and by test)
CHART_COLORS: dict[str, dict[str, str]] = {
    "light": {
        "INCLUDE": "#1B7F3B", "EXCLUDE": "#B3261E", "UNCERTAIN": "#B26A00",
        "ERROR": "#6B7280", "PRE_EXCLUDED": "#7C8CA8", "NOT_SCREENED": "#AAB2C0",
    },
    "dark": {
        "INCLUDE": "#5BD28A", "EXCLUDE": "#FF8A80", "UNCERTAIN": "#FFC857",
        "ERROR": "#A5AFBF", "PRE_EXCLUDED": "#7B8DB0", "NOT_SCREENED": "#4A586C",
    },
}  # fmt: skip
#: colour per run (comparing runs, not outcomes), cycled if there are more runs than colours
RUN_COLORS: dict[str, tuple[str, ...]] = {
    "light": (
        "#1B5FAE", "#B3261E", "#1B7F3B", "#8F5400", "#6E4E9E", "#0E7C86", "#A3338C", "#55606E",
    ),
    "dark": (
        "#7FB4F2", "#FF8A80", "#5BD28A", "#FFC857", "#C7A8FF", "#5FE0E8", "#F2A8E0", "#C3CBD6",
    ),
}  # fmt: skip
SCHEMA = "https://vega.github.io/schema/vega-lite/v5.json"
HEIGHT = 300

Label = Callable[[str], str]


def _theme(theme: str) -> str:
    return theme if theme in PALETTES else "light"


def config(theme: str) -> dict[str, Any]:
    """The Vega-Lite ``config``: transparent background, text and lines in the palette's colours."""
    p = PALETTES[_theme(theme)]
    return {
        "background": None,
        "font": "sans-serif",
        "view": {"stroke": None},
        "axis": {
            "labelColor": p["text"], "titleColor": p["text"], "gridColor": p["border"],
            "domainColor": p["muted"], "tickColor": p["muted"], "labelFontSize": 12,
            "titleFontSize": 13, "gridOpacity": 0.5,
        },
        "legend": {
            "labelColor": p["text"], "titleColor": p["text"], "labelFontSize": 12,
            "titleFontSize": 13,
        },
        "title": {"color": p["text"]},
        "header": {"labelColor": p["text"], "titleColor": p["text"]},
    }  # fmt: skip


def outcome_scale(theme: str, label: Label, present: Sequence[str] | None = None) -> dict[str, Any]:
    """A colour scale with the translated outcome names as domain."""
    names = [name for name in OUTCOMES if present is None or name in present]
    colours = CHART_COLORS[_theme(theme)]
    return {"domain": [label(n) for n in names], "range": [colours[n] for n in names]}


def run_scale(theme: str, run_ids: Sequence[str]) -> dict[str, Any]:
    """A stable, distinguishable colour per run id (cycles if there are more runs than colours)."""
    palette = RUN_COLORS[_theme(theme)]
    colours = [palette[i % len(palette)] for i in range(len(run_ids))]
    return {"domain": list(run_ids), "range": colours}


def _base(theme: str, data: list[dict[str, Any]], height: int = HEIGHT) -> dict[str, Any]:
    return {
        "$schema": SCHEMA,
        "config": config(theme),
        "data": {"values": data},
        "width": "container",
        "height": height,
    }


def donut(counts: Mapping[str, int], theme: str, label: Label) -> dict[str, Any]:
    """A ring chart of the outcomes (zero categories are left out)."""
    data = [
        {"label": label(name), "outcome": name, "count": count}
        for name, count in counts.items()
        if count
    ]
    spec = _base(theme, data, 320)
    spec["mark"] = {"type": "arc", "innerRadius": 70, "stroke": PALETTES[_theme(theme)]["bg"]}
    spec["encoding"] = {
        "theta": {"field": "count", "type": "quantitative", "stack": True},
        "color": {
            "field": "label",
            "type": "nominal",
            "scale": outcome_scale(theme, label, [str(d["outcome"]) for d in data]),
            "legend": {"title": None},
        },
        "tooltip": [
            {"field": "label", "type": "nominal"},
            {"field": "count", "type": "quantitative"},
        ],
    }
    return spec


def bars(
    items: Sequence[tuple[str, float]],
    theme: str,
    *,
    x_title: str,
    y_title: str,
    horizontal: bool = True,
) -> dict[str, Any]:
    """A simple bar chart of ``(category, value)`` pairs, largest first."""
    ordered = sorted(items, key=lambda item: item[1], reverse=True)
    data = [{"category": name, "value": value} for name, value in ordered]
    spec = _base(theme, data, max(160, min(600, 34 * len(data) + 50)) if horizontal else HEIGHT)
    spec["mark"] = {"type": "bar", "color": PALETTES[_theme(theme)]["primary"]}
    category = {"field": "category", "type": "nominal", "sort": None, "title": x_title}
    value = {"field": "value", "type": "quantitative", "title": y_title}
    spec["encoding"] = {
        ("y" if horizontal else "x"): category,
        ("x" if horizontal else "y"): value,
        "tooltip": [
            {"field": "category", "type": "nominal"},
            {"field": "value", "type": "quantitative"},
        ],
    }
    return spec


def stacked(
    table: Mapping[Any, Mapping[str, int]],
    theme: str,
    label: Label,
    *,
    category_title: str,
    count_title: str,
    horizontal: bool = False,
    normalise: bool = False,
    numeric_axis: bool = False,
) -> dict[str, Any]:
    """A stacked bar chart: per category, how many rows have each outcome.

    Args:
        table: ``category -> outcome -> count``.
        label: Translates an outcome name.
        normalise: Show shares (100 %) instead of counts.
        numeric_axis: The categories are numbers (years) and sorted as such.
    """
    data = [
        {"category": category, "label": label(outcome), "outcome": outcome, "count": count}
        for category, counts in table.items()
        for outcome, count in counts.items()
        if count
    ]
    spec = _base(theme, data, max(160, min(600, 34 * len(table) + 60)) if horizontal else HEIGHT)
    spec["mark"] = "bar"
    axis_type = "ordinal" if numeric_axis else "nominal"
    category = {
        "field": "category", "type": axis_type, "title": category_title,
        "sort": "ascending" if numeric_axis else "-y",
    }  # fmt: skip
    count = {
        "field": "count", "type": "quantitative", "title": count_title,
        "stack": "normalize" if normalise else True,
    }  # fmt: skip
    spec["encoding"] = {
        ("y" if horizontal else "x"): category,
        ("x" if horizontal else "y"): count,
        "color": {
            "field": "label",
            "type": "nominal",
            "scale": outcome_scale(theme, label, [str(d["outcome"]) for d in data]),
            "legend": {"title": None},
        },
        "tooltip": [
            {"field": "category", "type": axis_type},
            {"field": "label", "type": "nominal"},
            {"field": "count", "type": "quantitative"},
        ],
    }
    return spec


def histogram(
    bins: Sequence[Mapping[str, Any]],
    theme: str,
    label: Label,
    *,
    x_title: str,
    y_title: str,
    stack_outcomes: bool = True,
) -> dict[str, Any]:
    """A histogram from pre-counted bins (``bin_start``, ``bin_end``, ``outcome``, ``count``)."""
    data = [{**b, "label": label(str(b["outcome"]))} for b in bins]
    spec = _base(theme, data)
    spec["mark"] = {"type": "bar", "binSpacing": 1}
    spec["encoding"] = {
        "x": {
            "field": "bin_start",
            "type": "quantitative",
            "bin": {"binned": True},
            "title": x_title,
        },
        "x2": {"field": "bin_end"},
        "y": {"field": "count", "type": "quantitative", "aggregate": "sum", "title": y_title},
        "color": {
            "field": "label",
            "type": "nominal",
            "scale": outcome_scale(theme, label, sorted({str(b["outcome"]) for b in bins})),
            "legend": {"title": None},
        },
        "tooltip": [
            {"field": "bin_start", "type": "quantitative", "title": x_title},
            {"field": "label", "type": "nominal"},
            {"field": "count", "type": "quantitative"},
        ],
    }
    if not stack_outcomes:
        spec["encoding"]["color"] = {"value": PALETTES[_theme(theme)]["primary"]}
    return spec


def scatter(
    points: Sequence[Mapping[str, Any]],
    theme: str,
    label: Label,
    *,
    x_title: str,
    y_title: str,
) -> dict[str, Any]:
    """A scatter plot of year against abstract length, one dot per record, coloured by outcome."""
    data = [
        {"year": p["year"], "words": p["words"], "label": label(str(p["outcome"]))}
        for p in points
        if p.get("year")
    ]
    spec = _base(theme, data)
    spec["mark"] = {"type": "circle", "opacity": 0.55, "size": 45}
    spec["encoding"] = {
        "x": {"field": "year", "type": "quantitative", "scale": {"zero": False}, "title": x_title,
              "axis": {"format": "d"}},
        "y": {"field": "words", "type": "quantitative", "title": y_title},
        "color": {
            "field": "label",
            "type": "nominal",
            "scale": outcome_scale(theme, label, sorted({str(p["outcome"]) for p in points})),
            "legend": {"title": None},
        },
        "tooltip": [
            {"field": "year", "type": "quantitative", "title": x_title},
            {"field": "words", "type": "quantitative", "title": y_title},
            {"field": "label", "type": "nominal"},
        ],
    }  # fmt: skip
    return spec


def boxplot(
    points: Sequence[Mapping[str, Any]], theme: str, label: Label, *, y_title: str
) -> dict[str, Any]:
    """A box plot of abstract length per outcome."""
    present = sorted({str(p["outcome"]) for p in points})
    data = [{"label": label(str(p["outcome"])), "words": p["words"]} for p in points]
    spec = _base(theme, data)
    spec["mark"] = {"type": "boxplot", "extent": 1.5}
    spec["encoding"] = {
        "x": {"field": "label", "type": "nominal", "title": None, "axis": {"labelAngle": 0}},
        "y": {"field": "words", "type": "quantitative", "title": y_title},
        "color": {
            "field": "label",
            "type": "nominal",
            "scale": outcome_scale(theme, label, present),
            "legend": None,
        },
    }
    return spec


def run_bars(
    counts_by_run: Mapping[str, Mapping[str, int]],
    theme: str,
    label: Label,
    *,
    run_ids: Sequence[str],
    category_title: str,
    count_title: str,
    legend_title: str | None = None,
) -> dict[str, Any]:
    """Grouped bars of a category (for example the decision) per run, one colour per run.

    Args:
        counts_by_run: ``run_id -> category -> count`` (for example the decision counts of a run).
        run_ids: The runs, in the order of the colour scale and the groups within each category.
    """
    data = [
        {"category": label(category), "run": run_id, "count": count}
        for run_id in run_ids
        for category, count in counts_by_run.get(run_id, {}).items()
        if count
    ]
    spec = _base(theme, data)
    spec["mark"] = "bar"
    spec["encoding"] = {
        "x": {"field": "category", "type": "nominal", "title": category_title},
        "xOffset": {"field": "run", "sort": list(run_ids)},
        "y": {"field": "count", "type": "quantitative", "title": count_title},
        "color": {
            "field": "run",
            "type": "nominal",
            "scale": run_scale(theme, run_ids),
            "legend": {"title": legend_title},
        },
        "tooltip": [
            {"field": "run", "type": "nominal"},
            {"field": "category", "type": "nominal"},
            {"field": "count", "type": "quantitative"},
        ],
    }
    return spec
