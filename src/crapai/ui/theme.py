"""Look of the interface: light and dark palette, small and large text, and the saved choices.

Streamlit cannot switch its own theme while a page is open, so the interface draws its own look
with a style sheet that is built here from a **palette** (all colours in one place) and a **text
size**. Both are chosen with buttons in the sidebar and remembered between sessions in a small file
in the user's configuration folder (``ui_prefs.json``, next to the list of recent projects).

Contrast is a requirement, not a hope: every pair of text and background colour that the style
sheet uses is listed in :data:`CONTRAST_PAIRS`, and a test checks that each reaches at least 4.5:1
(the WCAG "AA" level for normal text) in both palettes.

Nothing here imports Streamlit; the style sheet is plain text that a page inserts.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from crapai.config.loader import default_user_config_path

logger = logging.getLogger(__name__)

THEMES = ("light", "dark")
SIZES = ("normal", "large")
PREFS_FILE = "ui_prefs.json"
#: root font size in pixels per text size; everything else is relative to it
FONT_PX = {"normal": 16, "large": 19}
MIN_CONTRAST = 4.5

#: colour names every palette must define
TOKENS = (
    "bg", "surface", "surface_alt", "text", "muted", "border", "primary", "on_primary", "link",
    "input_bg", "input_text", "sidebar_bg", "code_bg", "focus",
    "info_bg", "info_fg", "success_bg", "success_fg", "warning_bg", "warning_fg",
    "error_bg", "error_fg",
)  # fmt: skip

PALETTES: dict[str, dict[str, str]] = {
    "light": {
        "bg": "#FFFFFF", "surface": "#F3F5F9", "surface_alt": "#E6EBF3", "text": "#1B2430",
        "muted": "#4A5565", "border": "#B8C1CF", "primary": "#1F4FA3", "on_primary": "#FFFFFF",
        "link": "#0B4A9E", "input_bg": "#FFFFFF", "input_text": "#1B2430",
        "sidebar_bg": "#EAEFF7", "code_bg": "#EDF0F5", "focus": "#C25B00",
        "info_bg": "#E3EEFB", "info_fg": "#123E7C", "success_bg": "#E2F4E7",
        "success_fg": "#14532D", "warning_bg": "#FFF1D0", "warning_fg": "#5E3A00",
        "error_bg": "#FDE6E6", "error_fg": "#8A1C1C",
    },
    "dark": {
        "bg": "#0F141B", "surface": "#19212C", "surface_alt": "#243040", "text": "#E8EDF3",
        "muted": "#AEB8C6", "border": "#4A586C", "primary": "#7DB2FF", "on_primary": "#0B1220",
        "link": "#9CC6FF", "input_bg": "#1F2937", "input_text": "#E8EDF3",
        "sidebar_bg": "#141B24", "code_bg": "#0B1017", "focus": "#FFB454",
        "info_bg": "#12294A", "info_fg": "#BBD6FF", "success_bg": "#123524",
        "success_fg": "#B7F0CB", "warning_bg": "#3D2E0A", "warning_fg": "#FFE2A1",
        "error_bg": "#4A1717", "error_fg": "#FFC9C9",
    },
}  # fmt: skip

#: (text colour, background colour) pairs that the style sheet really uses
CONTRAST_PAIRS: tuple[tuple[str, str], ...] = (
    ("text", "bg"), ("text", "surface"), ("text", "surface_alt"), ("muted", "bg"),
    ("muted", "surface"), ("muted", "sidebar_bg"), ("text", "sidebar_bg"), ("on_primary", "primary"),
    ("link", "bg"), ("input_text", "input_bg"), ("text", "code_bg"),
    ("info_fg", "info_bg"), ("success_fg", "success_bg"), ("warning_fg", "warning_bg"),
    ("error_fg", "error_bg"), ("primary", "bg"), ("primary", "sidebar_bg"),
)  # fmt: skip


def _channel(value: int) -> float:
    s = value / 255
    return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4


def luminance(colour: str) -> float:
    """Relative luminance of ``#RRGGBB`` (WCAG definition)."""
    r, g, b = (int(colour[i : i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def contrast_ratio(first: str, second: str) -> float:
    """WCAG contrast ratio of two ``#RRGGBB`` colours (1 to 21)."""
    a, b = luminance(first), luminance(second)
    lighter, darker = max(a, b), min(a, b)
    return (lighter + 0.05) / (darker + 0.05)


@dataclass
class UiPrefs:
    """The choices that survive a restart: language, light or dark, text size.

    Args:
        path: The JSON file (default: ``~/.config/crapai/ui_prefs.json``).
    """

    path: Path = field(default_factory=lambda: default_user_config_path().with_name(PREFS_FILE))

    def load(self) -> dict[str, str]:
        """The saved choices; a missing or damaged file, or an unknown value, is ignored."""
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(data, dict):
            return {}
        allowed = {"lang": ("en", "de"), "theme": THEMES, "size": SIZES}
        return {k: v for k, v in data.items() if k in allowed and v in allowed[k]}

    def save(self, **choices: str) -> None:
        """Merge ``choices`` into the file; problems are logged, never raised."""
        merged = {**self.load(), **{k: v for k, v in choices.items() if v}}
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(merged, indent=2), encoding="utf-8")
        except OSError as exc:
            logger.warning("Cannot save the interface choices (%s)", type(exc).__name__)


def build_css(theme: str = "light", size: str = "normal", browser_theme: str | None = None) -> str:
    """The style sheet for a palette and a text size.

    Args:
        theme: ``light`` or ``dark`` (the colours of the page).
        size: ``normal`` or ``large`` (the root font size; everything scales with it).
        browser_theme: The theme Streamlit itself is drawn in (``light``/``dark``) if known.
            Tables are drawn by Streamlit on a canvas that this style sheet cannot colour; if
            their theme differs from the chosen one they are inverted so that they stay readable.
    """
    theme = theme if theme in PALETTES else "light"
    p = PALETTES[theme]
    px = FONT_PX[size if size in FONT_PX else "normal"]
    flip = browser_theme in THEMES and browser_theme != theme
    table_rule = (
        '[data-testid="stDataFrame"] { filter: invert(1) hue-rotate(180deg); }' if flip else ""
    )
    return f"""
html {{ font-size: {px}px; }}
:root {{ color-scheme: {theme}; }}
.stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"] {{
  background: {p["bg"]}; color: {p["text"]};
}}
[data-testid="stHeader"] {{ background: {p["bg"]}; }}
[data-testid="stHeader"] * {{ color: {p["text"]} !important; }}
[data-testid="stSidebar"], [data-testid="stSidebar"] > div {{ background: {p["sidebar_bg"]}; }}
.stApp p, .stApp li, .stApp label, [data-testid="stMarkdownContainer"] {{
  color: {p["text"]};
}}
.stApp h1, .stApp h2, .stApp h3, .stApp h4 {{
  color: {p["text"]} !important; font-weight: 650; line-height: 1.25; letter-spacing: 0;
}}
.stApp h1 {{ font-size: 1.9rem !important; margin: 0 0 .5rem 0; }}
.stApp h2 {{ font-size: 1.5rem !important; }}
.stApp h3 {{ font-size: 1.2rem !important; }}
.stApp p, .stApp li, .stApp label {{ font-size: 1rem; line-height: 1.55; }}
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] * {{
  color: {p["muted"]} !important; font-size: .9rem !important;
}}
a, a * {{ color: {p["link"]} !important; text-decoration: underline; }}
code, pre, [data-testid="stCode"], [data-testid="stCode"] * {{
  background: {p["code_bg"]} !important; color: {p["text"]} !important;
}}
hr {{ border-color: {p["border"]}; }}

/* tiles with numbers: long values wrap instead of being cut off */
[data-testid="stMetric"] {{
  background: {p["surface"]}; border: 1px solid {p["border"]}; border-radius: .6rem;
  padding: .6rem .8rem;
}}
[data-testid="stMetricLabel"], [data-testid="stMetricLabel"] * {{
  color: {p["muted"]} !important; font-size: .85rem !important;
}}
[data-testid="stMetricValue"], [data-testid="stMetricValue"] * {{
  color: {p["text"]} !important; font-size: 1.3rem !important; font-weight: 650;
  white-space: normal !important; overflow: visible !important; text-overflow: clip !important;
  overflow-wrap: anywhere; line-height: 1.25;
}}

/* inputs */
input, textarea, [data-baseweb="select"] > div, [data-baseweb="input"],
[data-baseweb="textarea"], [data-baseweb="base-input"] {{
  background: {p["input_bg"]} !important; color: {p["input_text"]} !important;
  border-color: {p["border"]} !important;
}}
input::placeholder, textarea::placeholder {{ color: {p["muted"]} !important; opacity: 1; }}
[data-baseweb="select"] *, [data-baseweb="input"] * {{ color: {p["input_text"]} !important; }}
[data-baseweb="popover"] *, [data-baseweb="menu"], ul[role="listbox"], li[role="option"] {{
  background: {p["surface"]}; color: {p["text"]} !important;
}}
li[role="option"]:hover, li[role="option"][aria-selected="true"] {{
  background: {p["surface_alt"]};
}}
[data-testid="stCheckbox"] span, [data-testid="stRadio"] label {{ color: {p["text"]} !important; }}
[data-testid="stTooltipIcon"] button {{ background: transparent !important; border: 0 !important; }}
[data-testid="stTooltipIcon"] svg, [data-testid="stTooltipIcon"] svg * {{
  fill: none !important; stroke: {p["muted"]} !important; color: {p["muted"]} !important;
}}
[data-testid="stFileUploaderDropzone"] {{
  background: {p["surface"]}; border: 1px dashed {p["border"]};
}}
[data-testid="stFileUploaderDropzone"] * {{ color: {p["text"]} !important; }}
*:focus-visible {{ outline: 3px solid {p["focus"]} !important; outline-offset: 2px; }}

/* buttons: filled = main action, outlined = other actions */
button[data-testid^="stBaseButton-"]:not([data-testid*="primary"]) {{
  background: {p["surface"]} !important; color: {p["text"]} !important;
  border: 1px solid {p["border"]} !important; border-radius: .5rem; font-weight: 600;
  min-height: 2.4rem;
}}
button[data-testid^="stBaseButton-"]:not([data-testid*="primary"]):hover {{
  border-color: {p["primary"]} !important; background: {p["surface_alt"]} !important;
}}
button[data-testid^="stBaseButton-"] * {{ color: inherit !important; }}
button[data-testid*="primary"] {{
  background: {p["primary"]} !important; color: {p["on_primary"]} !important;
  border: 1px solid {p["primary"]} !important; border-radius: .5rem; font-weight: 600;
  min-height: 2.4rem;
}}
button:disabled {{ opacity: .55; cursor: not-allowed; }}
[data-testid="stTooltipContent"], [data-testid="stTooltipContent"] * {{
  background: {p["surface_alt"]} !important; color: {p["text"]} !important;
}}
[data-testid="stSidebarCollapseButton"] *, [data-testid="stExpandSidebarButton"] * {{
  color: {p["text"]} !important;
}}

/* sidebar menu */
[data-testid="stSidebar"] button[data-testid^="stBaseButton-"] {{
  width: 100%; justify-content: flex-start; text-align: left; padding: .45rem .8rem;
}}
[data-testid="stSidebar"] button[data-testid*="primary"] {{ box-shadow: inset 4px 0 0 {p["focus"]}; }}
.crapai-title {{ font-size: 1.15rem; font-weight: 650; color: {p["text"]}; margin: 0 0 .4rem 0; overflow-wrap: anywhere; }}
.crapai-brand {{ font-size: 1.35rem; font-weight: 700; color: {p["text"]}; margin: .2rem 0 .1rem 0; }}
.crapai-brand-sub {{ font-size: .85rem; color: {p["muted"]}; margin-bottom: .8rem; }}
.crapai-nav-title {{
  font-size: .78rem; font-weight: 700; letter-spacing: .06em; text-transform: uppercase;
  color: {p["muted"]}; margin: 1rem 0 .3rem 0;
}}
.crapai-project {{
  font-size: .85rem; color: {p["muted"]}; overflow-wrap: anywhere; margin: .6rem 0;
}}

/* expanders, forms, tabs */
[data-testid="stExpander"], [data-testid="stForm"] {{
  background: {p["surface"]}; border: 1px solid {p["border"]}; border-radius: .6rem;
}}
[data-testid="stExpander"] summary, [data-testid="stExpander"] summary * {{
  color: {p["text"]} !important; font-weight: 600;
}}
[data-testid="stExpander"] summary, [data-testid="stExpander"] details {{
  background: {p["surface"]} !important; border-radius: .6rem;
}}
[data-testid="stExpander"] summary:hover {{ background: {p["surface_alt"]} !important; }}
[data-testid="stProgress"] > div > div {{ background: {p["surface_alt"]} !important; }}
[data-testid="stProgress"] > div > div > div {{ background: {p["primary"]} !important; }}

/* notices (own boxes instead of Streamlit's alerts, whose colours depend on its theme) */
.crapai-notice {{
  display: flex; gap: .65rem; align-items: flex-start; padding: .75rem 1rem; margin: .45rem 0;
  border-radius: .55rem; border: 1px solid; font-size: 1rem; line-height: 1.5;
  overflow-wrap: anywhere;
}}
.crapai-notice .crapai-icon {{ font-size: 1.1rem; line-height: 1.4; }}
.crapai-notice div, .crapai-notice span {{ color: inherit !important; }}
.crapai-info    {{ background: {p["info_bg"]};    color: {p["info_fg"]};    border-color: {p["info_fg"]}; }}
.crapai-success {{ background: {p["success_bg"]}; color: {p["success_fg"]}; border-color: {p["success_fg"]}; }}
.crapai-warning {{ background: {p["warning_bg"]}; color: {p["warning_fg"]}; border-color: {p["warning_fg"]}; }}
.crapai-error   {{ background: {p["error_bg"]};   color: {p["error_fg"]};   border-color: {p["error_fg"]}; }}
{table_rule}
"""
