"""Look of the interface (palette, contrast, saved choices) and the cover around Streamlit."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from crapai.ui.kit import Themed, help_id, notice_html
from crapai.ui.theme import (
    CONTRAST_PAIRS,
    FONT_PX,
    MIN_CONTRAST,
    PALETTES,
    SIZES,
    THEMES,
    TOKENS,
    UiPrefs,
    build_css,
    contrast_ratio,
    luminance,
)

# --- palette and contrast ---------------------------------------------------------------------------


@pytest.mark.parametrize("theme", THEMES)
def test_every_palette_defines_every_colour(theme: str) -> None:
    assert set(PALETTES[theme]) == set(TOKENS)
    assert all(len(v) == 7 and v.startswith("#") for v in PALETTES[theme].values())


@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("pair", CONTRAST_PAIRS)
def test_text_and_background_reach_the_aa_contrast(theme: str, pair: tuple[str, str]) -> None:
    palette = PALETTES[theme]
    ratio = contrast_ratio(palette[pair[0]], palette[pair[1]])
    assert ratio >= MIN_CONTRAST, f"{theme}: {pair} has only {ratio:.2f}:1"


def test_contrast_maths() -> None:
    assert contrast_ratio("#000000", "#FFFFFF") == pytest.approx(21.0)
    assert contrast_ratio("#777777", "#777777") == pytest.approx(1.0)
    assert luminance("#FFFFFF") == pytest.approx(1.0) and luminance("#000000") == 0.0
    assert contrast_ratio("#123456", "#ABCDEF") == contrast_ratio("#ABCDEF", "#123456")


def test_the_two_designs_really_differ() -> None:
    assert luminance(PALETTES["light"]["bg"]) > 0.8 > 0.2 > luminance(PALETTES["dark"]["bg"])
    assert luminance(PALETTES["light"]["text"]) < luminance(PALETTES["dark"]["text"])


# --- style sheet --------------------------------------------------------------------------------------


@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("size", SIZES)
def test_the_style_sheet_uses_the_palette_and_size(theme: str, size: str) -> None:
    css = build_css(theme, size)
    assert f"font-size: {FONT_PX[size]}px" in css
    assert PALETTES[theme]["bg"] in css and PALETTES[theme]["primary"] in css
    assert css.count("{") == css.count("}")  # no broken rule
    assert "{{" not in css and "}}" not in css  # no unformatted f-string leftovers


def test_large_text_is_larger_than_normal() -> None:
    assert FONT_PX["large"] > FONT_PX["normal"]


def test_unknown_values_fall_back_to_light_and_normal() -> None:
    assert build_css("neon", "huge") == build_css("light", "normal")


def test_tables_are_inverted_only_when_streamlit_draws_the_other_theme() -> None:
    flip = "filter: invert(1) hue-rotate(180deg)"
    assert flip in build_css("dark", "normal", browser_theme="light")
    assert flip in build_css("light", "normal", browser_theme="dark")
    assert flip not in build_css("dark", "normal", browser_theme="dark")
    assert flip not in build_css("dark", "normal", browser_theme=None)


def test_long_values_in_tiles_wrap_instead_of_being_cut() -> None:
    css = build_css("light", "normal")
    assert "stMetricValue" in css and "white-space: normal" in css


def test_notices_have_a_box_for_every_kind() -> None:
    css = build_css("dark", "normal")
    for kind in ("info", "success", "warning", "error"):
        assert f".crapai-{kind}" in css


# --- saved choices ------------------------------------------------------------------------------------


def test_choices_are_saved_and_merged(tmp_path: Path) -> None:
    prefs = UiPrefs(tmp_path / "sub" / "ui_prefs.json")
    assert prefs.load() == {}
    prefs.save(lang="de", theme="dark", size="large")
    prefs.save(theme="light")
    assert prefs.load() == {"lang": "de", "theme": "light", "size": "large"}


@pytest.mark.parametrize(
    "content", ["", "{", "[1]", '"x"', '{"theme": "neon", "lang": "fr", "size": 3, "other": 1}']
)
def test_damaged_or_unknown_choices_are_ignored(tmp_path: Path, content: str) -> None:
    path = tmp_path / "ui_prefs.json"
    path.write_text(content, encoding="utf-8")
    assert UiPrefs(path).load() == {}


def test_a_file_that_cannot_be_written_does_not_stop_the_interface(tmp_path: Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("x", encoding="utf-8")
    UiPrefs(blocker / "ui_prefs.json").save(lang="de")  # must not raise


# --- the cover around Streamlit -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "key,ident",
    [
        ("nav_data", "nav_data"),
        ("set::dedup.fuzzy.enabled::3", "setting.dedup_fuzzy_enabled"),
        ("set::run.batch_size::0", "setting.run_batch_size"),
        ("recent-4", "recent"),
        ("label-my file.ris", "label"),
        ("run_start", "run_start"),
    ],
)
def test_help_ids(key: str, ident: str) -> None:
    assert help_id(key) == ident


def test_notices_escape_html_and_keep_bold_and_line_breaks() -> None:
    html = notice_html("warning", "<script>x</script> **fat**\nsecond")
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "<b>fat</b>" in html and "<br>" in html and "crapai-warning" in html


class FakeStreamlit:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def __getattr__(self, name: str) -> Any:
        def call(*args: Any, **kwargs: Any) -> Any:
            self.calls.append((name, args, kwargs))
            if name == "columns":
                return [FakeStreamlit(), FakeStreamlit()]
            return False

        return call


def test_widgets_with_a_key_get_their_help_text() -> None:
    fake = FakeStreamlit()
    ui = Themed(fake, {"run_start": "Starts the run."}.get)
    ui.button("Start", key="run_start")
    assert fake.calls[0][2]["help"] == "Starts the run."
    assert not ui.missing


def test_a_widget_without_a_help_text_is_recorded() -> None:
    fake = FakeStreamlit()
    ui = Themed(fake, lambda _ident: None)
    ui.text_input("Name", key="nobody_wrote_this")
    assert ui.missing == {"nobody_wrote_this"}
    assert "help" not in fake.calls[0][2]


def test_an_explicit_help_is_kept_and_widgets_without_key_are_left_alone() -> None:
    fake = FakeStreamlit()
    ui = Themed(fake, lambda _ident: "automatic")
    ui.checkbox("A", key="a", help="mine")
    ui.checkbox("B")
    assert fake.calls[0][2]["help"] == "mine" and "help" not in fake.calls[1][2]


def test_columns_are_covered_too_and_share_the_record_of_missing_help() -> None:
    fake = FakeStreamlit()
    ui = Themed(fake, lambda _ident: None)
    left, _right = ui.columns(2)
    left.selectbox("X", [1], key="in_a_column")
    assert ui.missing == {"in_a_column"}


def test_notice_methods_draw_html_through_markdown() -> None:
    fake = FakeStreamlit()
    ui = Themed(fake, lambda _ident: None)
    for kind in ("info", "success", "warning", "error"):
        getattr(ui, kind)(f"text {kind}")
    names = [name for name, _args, _kwargs in fake.calls]
    assert names == ["markdown"] * 4
    assert all(call[2]["unsafe_allow_html"] for call in fake.calls)
    assert "crapai-error" in fake.calls[3][1][0]


def test_everything_else_passes_through() -> None:
    fake = FakeStreamlit()
    ui = Themed(fake, lambda _ident: None)
    ui.header("Title")
    assert fake.calls == [("header", ("Title",), {})]
