# PORTED from SARA-App: i18n.py
# Changes: fallback import path; texts/ now lives inside this package (saralocal/i18n/texts/).
# Reference original (unchanged): reference/sara-app/i18n.py
# i18n.py - Translation module for texts
"""
Tiny i18n loader with layered fallbacks:
1) Python defaults from texts/fallback.py
2) en.yaml overlays those defaults (if present)
3) <lang>.yaml overlays again (if lang != "en")

No Streamlit dependency. Works in tests/CLI as well.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from functools import lru_cache
import logging
import os
import time

logger = logging.getLogger(__name__)

# Optional YAML dependency: app still runs without it (fallbacks only)
try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None

# Python fallback defaults (developer-maintained)
from saralocal.i18n.texts.fallback import DEFAULT_TEXTS


def _deep_merge(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively merge dict b into dict a (b wins), return a new dict."""
    out = dict(a)
    for k, v in (b or {}).items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _resolve_texts_path(lang: str, base_dir: Optional[str]) -> Path:
    """
    Resolve <base_dir>/texts/<lang>.yaml.
    If base_dir is None, assume this file lives at project root and texts/ is sibling.
    """
    if base_dir:
        base = Path(base_dir).resolve()
    else:
        # Project root = directory containing this file
        base = Path(__file__).resolve().parent
    return (base / "texts" / f"{lang}.yaml").resolve()


def _load_yaml_dict(path: Path) -> Dict[str, Any]:
    """Load YAML and return dict or {}. Never raise, logs on issues."""
    if yaml is None:
        logger.debug("PyYAML not installed; skipping YAML load for %s", path)
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
            if not isinstance(data, dict):
                logger.warning("YAML at %s is not a dict. Ignoring.", path)
                return {}
            return data
    except FileNotFoundError:
        logger.debug("YAML not found at %s", path)
        return {}
    except Exception as e:  # pragma: no cover
        logger.warning("Failed to read YAML %s (%s). Ignoring.", path, e)
        return {}


def _files_mtime_token(paths: List[Path]) -> float:
    """Compute a cache-busting token from file modification times."""
    mtimes = []
    for p in paths:
        try:
            mtimes.append(p.stat().st_mtime)
        except Exception:
            mtimes.append(0.0)
    return sum(mtimes)


@lru_cache(maxsize=32)
def _load_layered(lang: str, base_dir: Optional[str], mtime_token: float) -> Dict[str, Any]:
    """
    Internal cache entry keyed by (lang, base_dir, mtime_token).
    mtime_token ensures cache refresh when YAML files are edited.
    """
    # 1) start from Python defaults
    texts = dict(DEFAULT_TEXTS)

    # 2) overlay en.yaml
    en_path = _resolve_texts_path("en", base_dir)
    texts = _deep_merge(texts, _load_yaml_dict(en_path))

    # 3) overlay lang.yaml if different
    lang = (lang or "en").lower()
    if lang != "en":
        lang_path = _resolve_texts_path(lang, base_dir)
        texts = _deep_merge(texts, _load_yaml_dict(lang_path))

    return texts


class I18n:
    """
    Minimal i18n facade:
      i18n = I18n(base_dir=project_root) ; texts = i18n.load("en")
      i18n.t("sections.project.header")
      i18n.tf("sections.upload.database_field.label", filename="pubmed.ris")
      i18n.lst("sections.screening.review_mode.options")
      missing = i18n.validate(required_paths)
    """

    def __init__(self, base_dir: Optional[str] = None):
        self.base_dir = base_dir

    def load(self, lang: str = "en") -> Dict[str, Any]:
        """Load layered texts with cache busting when files change."""
        en_path = _resolve_texts_path("en", self.base_dir)
        lang_path = _resolve_texts_path(lang, self.base_dir) if lang.lower() != "en" else None
        token = _files_mtime_token([p for p in [en_path, lang_path] if p])
        self._texts = _load_layered(lang, self.base_dir, token)
        self._lang = lang
        self._paths = {"en": en_path, lang: lang_path} if lang_path else {"en": en_path}
        return self._texts

    # -------------- getters --------------

    def t(self, path: str) -> str:
        v = self._get_nested(path)
        return str(v) if isinstance(v, (str, int, float)) else ""

    def tf(self, path: str, **kwargs) -> str:
        return self.t(path).format(**kwargs)

    def lst(self, path: str) -> List[str]:
        v = self._get_nested(path)
        return [str(x) for x in v] if isinstance(v, list) else []

    # -------------- validation -------------

    def validate(self, required_paths: List[str]) -> List[str]:
        """
        Return a list of missing/empty keys (doesn't raise).
        Let the GUI decide whether to warn or stop.
        """
        missing: List[str] = []
        for p in required_paths:
            v = self._get_nested(p)
            if v is None:
                missing.append(p)
            elif isinstance(v, str) and not v.strip():
                missing.append(p)
            elif isinstance(v, list) and len(v) == 0:
                missing.append(p)
        return missing

    # -------------- helpers ----------------

    def _get_nested(self, dotted: str) -> Any:
        node = getattr(self, "_texts", {})
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return None
            node = node[part]
        return node

    # Expose resolved paths for diagnostics
    @property
    def resolved_paths(self) -> Dict[str, Optional[Path]]:
        return getattr(self, "_paths", {})
