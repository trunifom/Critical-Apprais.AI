"""Tests for the PRISMA flow picture (PNG/SVG)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from crapai.errors import ConfigError
from crapai.io.writers.prisma_image import write_prisma_image
from crapai.prisma.flow import PrismaFlow

pytest.importorskip("matplotlib")


def flow(**overrides: int) -> PrismaFlow:
    values: dict[str, int] = {
        "records_identified_total": 100,
        "duplicates_removed": 20,
        "records_screened_title_abstract": 75,
        "records_excluded_title_abstract": 50,
        "studies_included_in_review": 15,
    }
    values.update(overrides)
    return PrismaFlow(**values)  # type: ignore[arg-type]


def svg_text(path: Path, data: PrismaFlow) -> str:
    write_prisma_image(path, data, "svg")
    return path.read_text(encoding="utf-8")


def test_png_has_the_right_magic_bytes(tmp_path: Path) -> None:
    path = tmp_path / "flow.png"
    write_prisma_image(path, flow(), "png")
    assert path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


def test_svg_contains_the_flow_numbers_as_text(tmp_path: Path) -> None:
    text = svg_text(tmp_path / "flow.svg", flow())
    assert "Records identified" in text and "n = 100" in text
    assert "n = 20" in text  # duplicates removed
    assert "n = 50" in text  # excluded at title/abstract
    assert "n = 15" in text  # included


def test_the_fulltext_stage_is_shown_only_when_it_happened(tmp_path: Path) -> None:
    without = svg_text(tmp_path / "a.svg", flow())
    assert "eligibility" not in without

    with_fulltext = svg_text(
        tmp_path / "b.svg",
        flow(reports_assessed_for_eligibility=25, reports_excluded_fulltext=10),
    )
    assert "eligibility" in with_fulltext
    assert "n = 25" in with_fulltext and "n = 10" in with_fulltext


def test_other_reasons_removed_before_screening_are_shown_alongside_duplicates(
    tmp_path: Path,
) -> None:
    text = svg_text(
        tmp_path / "flow.svg", flow(records_removed_before_screening_other=7)
    )
    assert "Removed for other reasons" in text and "n = 7" in text


def test_an_unknown_image_format_is_e203(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as info:
        write_prisma_image(tmp_path / "flow.gif", flow(), "gif")
    assert info.value.code == "E203"


def test_without_matplotlib_is_a_clear_e203(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in list(sys.modules):
        if name == "matplotlib" or name.startswith("matplotlib."):
            monkeypatch.setitem(sys.modules, name, None)
    with pytest.raises(ConfigError) as info:
        write_prisma_image(tmp_path / "flow.png", flow(), "png")
    assert info.value.code == "E203" and "matplotlib" in info.value.user_message
