"""PRISMA 2020 flow diagram as a picture (PNG or SVG), next to the existing JSON export.

Draws the same numbers ``crapai export --what flow`` already writes as ``prisma_flow.json``
(:class:`~crapai.prisma.flow.PrismaFlow`) as a simple top-to-bottom box diagram: identified ->
duplicates removed -> screened -> excluded (title/abstract) -> [assessed for eligibility ->
excluded (full text), only shown once any full-text screening happened] -> included. Each
"excluded" box sits beside the main flow with an arrow into it, as PRISMA's own template does.

Uses the object-oriented matplotlib API directly (``Figure``/``FigureCanvasAgg``), never
``pyplot``: a CLI tool must not depend on a global, process-wide "current figure"/backend state
that ``pyplot`` manages, and this way nothing here could ever try to open a display window.
"""

from __future__ import annotations

import logging
from pathlib import Path

from crapai.errors import ConfigError
from crapai.prisma.flow import PrismaFlow
from crapai.project.atomic import WriteResult, atomic_write_bytes

logger = logging.getLogger(__name__)

BOX_WIDTH = 3.4
BOX_HEIGHT = 0.8
SIDE_BOX_WIDTH = 2.6
V_GAP = 0.5
FIG_WIDTH = 7.5


def _counted(label: str, count: int) -> str:
    return f"{label}\n(n = {count})"


def _main_boxes(flow: PrismaFlow) -> list[str]:
    boxes = [
        _counted("Records identified", flow.records_identified_total),
        _counted("Records screened\n(title/abstract)", flow.records_screened_title_abstract),
    ]
    if flow.reports_assessed_for_eligibility or flow.reports_excluded_fulltext:
        boxes.append(
            _counted(
                "Reports assessed for\neligibility (full text)",
                flow.reports_assessed_for_eligibility,
            )
        )
    boxes.append(_counted("Studies included\nin review", flow.studies_included_in_review))
    return boxes


def _side_boxes(flow: PrismaFlow) -> dict[int, str]:
    """Main-box index (the box the arrow leaves from) -> the excluded/removed box beside it."""
    sides = {0: _counted("Duplicates removed", flow.duplicates_removed)}
    if flow.records_removed_before_screening_other:
        sides[0] = (
            f"{_counted('Duplicates removed', flow.duplicates_removed)}\n"
            + _counted("Removed for other reasons", flow.records_removed_before_screening_other)
        )
    sides[1] = _counted("Excluded", flow.records_excluded_title_abstract)
    if flow.reports_assessed_for_eligibility or flow.reports_excluded_fulltext:
        sides[2] = _counted("Excluded", flow.reports_excluded_fulltext)
    return sides


def _draw(flow: PrismaFlow) -> object:
    try:
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from matplotlib.figure import Figure
        from matplotlib.patches import FancyBboxPatch
    except ImportError as exc:
        raise ConfigError(
            "Drawing the PRISMA flow needs the package matplotlib",
            code="E203",
            hint='Install it with: pip install "crapai[stats]", or export --what flow '
            "(JSON) instead.",
        ) from exc

    main = _main_boxes(flow)
    sides = _side_boxes(flow)
    height = len(main) * (BOX_HEIGHT + V_GAP) + V_GAP
    figure = Figure(figsize=(FIG_WIDTH, height), dpi=150)
    FigureCanvasAgg(figure)
    axes = figure.add_axes((0, 0, 1, 1))
    axes.set_xlim(0, FIG_WIDTH)
    axes.set_ylim(0, height)
    axes.axis("off")

    centre_x = FIG_WIDTH * 0.32
    tops = []
    for index, text in enumerate(main):
        top = height - V_GAP - index * (BOX_HEIGHT + V_GAP)
        tops.append(top)
        _box(axes, FancyBboxPatch, centre_x, top, BOX_WIDTH, text)
        if index > 0:
            axes.annotate(
                "", xy=(centre_x, top), xytext=(centre_x, tops[index - 1] - BOX_HEIGHT),
                arrowprops={"arrowstyle": "-|>", "color": "black", "lw": 1.2},
            )  # fmt: skip
    side_x = centre_x + BOX_WIDTH / 2 + 0.6 + SIDE_BOX_WIDTH / 2
    for main_index, side_text in sides.items():
        top = tops[main_index]
        _box(axes, FancyBboxPatch, side_x, top, SIDE_BOX_WIDTH, side_text)
        axes.annotate(
            "", xy=(side_x - SIDE_BOX_WIDTH / 2, top - BOX_HEIGHT / 2),
            xytext=(centre_x + BOX_WIDTH / 2, top - BOX_HEIGHT / 2),
            arrowprops={"arrowstyle": "-|>", "color": "black", "lw": 1.0},
        )  # fmt: skip
    return figure


def _box(axes: object, fancy_bbox_cls: type, x: float, top: float, width: float, text: str) -> None:
    patch = fancy_bbox_cls(
        (x - width / 2, top - BOX_HEIGHT), width, BOX_HEIGHT,
        boxstyle="round,pad=0.04,rounding_size=0.05",
        linewidth=1.2, edgecolor="black", facecolor="#F3F5F9",
    )  # fmt: skip
    axes.add_patch(patch)  # type: ignore[attr-defined]
    axes.text(x, top - BOX_HEIGHT / 2, text, ha="center", va="center", fontsize=9)  # type: ignore[attr-defined]


def write_prisma_image(path: Path, flow: PrismaFlow, fmt: str = "png") -> WriteResult:
    """Write the PRISMA flow as a PNG or SVG picture (atomic; a locked target gives an alternative).

    Raises:
        ConfigError: E203 if ``matplotlib`` is not installed, or ``fmt`` is neither png nor svg.
        StorageError: E401/E403 from the atomic write.
    """
    if fmt not in ("png", "svg"):
        raise ConfigError(
            f"Unknown image format '{fmt}' for the PRISMA flow (valid: png, svg)", code="E203"
        )
    figure = _draw(flow)
    import io as _io  # only needed once matplotlib is already confirmed present

    buffer = _io.BytesIO()
    figure.savefig(buffer, format=fmt, bbox_inches="tight")  # type: ignore[attr-defined]
    logger.info("Drawing the PRISMA flow as %s", fmt)
    return atomic_write_bytes(path, buffer.getvalue())
