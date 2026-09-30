"""Framework-aware inclusion/exclusion criteria with optional i18n.

Ported from SARA-App (``core/criteria_template.py``, kept unchanged in ``reference/``) with the
i18n import path changed and the custom-element methods fixed to keep ``fields`` in step.

This module is UI-agnostic (no Streamlit import). It integrates with the project i18n loader
(if present) to fetch:
  - framework field lists: screening.framework_fields.<FRAME>
  - prompt labels:         criteria.prompt.*

If i18n (or YAML) is not available, robust Python defaults are used.

Backwards compatibility:
- Keeps the public API of the predecessor (constructor parameters, methods).
- Adds optional i18n params: lang, texts_base_dir, texts.
"""

from __future__ import annotations

from typing import Optional, Dict, Any, List
from functools import lru_cache
import logging

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Python-level defaults (used when i18n/YAML is absent or incomplete)
# ──────────────────────────────────────────────────────────────────────────────

# Canonical field sets per framework
_DEFAULT_FRAMEWORK_FIELDS: Dict[str, List[str]] = {
    "PICOS": ["Population", "Intervention", "Comparison", "Outcome", "Study Design"],
    "SPIDER": ["Sample", "Phenomenon of Interest", "Design", "Evaluation", "Research Type"],
    "PECO": ["Population", "Exposure", "Comparison", "Outcome"],
    "PIRD": ["Population", "Index Test", "Reference Standard", "Diagnosis"],
    "CUSTOM": [],  # CUSTOM is dynamic from user-provided `custom_fields`
}

# Default prompt labels for to_prompt_string()
_DEFAULT_PROMPT_TEXTS: Dict[str, str] = {
    "header": "Screening Criteria",
    "framework_label": "Framework",
    "inclusion_header": "Inclusion",
    "exclusion_header": "Exclusion",
    "field_separator": "",  # set to '---' in YAML if you want visual separators
    "empty_value": "-",  # shown when a field is empty
}


# ──────────────────────────────────────────────────────────────────────────────
# Minimal i18n access (optional)
# We try to import the project-level i18n loader; if it is not available, we fall back.
# ──────────────────────────────────────────────────────────────────────────────


def _deep_get(d: Dict[str, Any], dotted: str) -> Any:
    """Return nested value by dot path, or None if missing."""
    node = d
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


@lru_cache(maxsize=16)
def _load_texts(lang: str = "en", base_dir: Optional[str] = None) -> Dict[str, Any]:
    """
    Attempt to load the layered i18n dict using the project's i18n loader.
    On failure (import error, runtime error, missing files), return a minimal dict
    containing only the keys this class cares about (with Python defaults).
    """
    try:
        # Lazy import so this file stays reusable in other contexts (tests, CLI)
        from crapai.i18n import I18n  # type: ignore

        i18n = I18n(base_dir=base_dir)
        return i18n.load(lang)
    except Exception as e:
        # Fallback: a minimal i18n tree with defaults we need
        logger.warning("i18n not available (%s). Using built-in defaults for CriteriaTemplate.", e)
        return {
            "screening": {
                "framework_fields": {
                    "PICOS": _DEFAULT_FRAMEWORK_FIELDS["PICOS"],
                    "SPIDER": _DEFAULT_FRAMEWORK_FIELDS["SPIDER"],
                    "PECO": _DEFAULT_FRAMEWORK_FIELDS["PECO"],
                    "PIRD": _DEFAULT_FRAMEWORK_FIELDS["PIRD"],
                    # CUSTOM omitted intentionally (dynamic)
                }
            },
            "criteria": {"prompt": dict(_DEFAULT_PROMPT_TEXTS)},
        }


def _texts_get_list(
    texts: Dict[str, Any], path: str, default: Optional[List[str]] = None
) -> List[str]:
    val = _deep_get(texts, path)
    if isinstance(val, list):
        return [str(x) for x in val]
    return list(default or [])


def _texts_get_str(texts: Dict[str, Any], path: str, default: Optional[str] = None) -> str:
    val = _deep_get(texts, path)
    if isinstance(val, (str, int, float)):
        return str(val)
    return default or ""


# ──────────────────────────────────────────────────────────────────────────────
# Core model
# ──────────────────────────────────────────────────────────────────────────────


class CriteriaTemplate:
    """
    Encapsulates inclusion & exclusion criteria for a chosen framework.

    Args
    ----
    template_type : str
        One of {"PICOS", "SPIDER", "PECO", "PIRD", "CUSTOM"} (case-insensitive).
    custom_fields : list[str] | None
        Only used if template_type == "CUSTOM". These become the active fields.
    initial_inclusion : dict[str, str] | None
        Optional pre-filled inclusion values by field name.
    initial_exclusion : dict[str, str] | None
        Optional pre-filled exclusion values by field name.
    selected_elements : list[str] | None
        Optional list of custom element names; kept for backward-compatibility.
    lang : str
        Locale code for i18n (e.g., "en", "de"). Defaults to "en".
    texts_base_dir : str | None
        Base dir for resolving `texts/<lang>.yaml` via the project i18n loader.
    texts : dict | None
        Preloaded i18n tree. If provided, the project i18n loader is not used.

    Notes
    -----
    - Field order is defined by the framework fields (from i18n or defaults).
    - Unknown field names in update_* raise KeyError to surface typos early.
    """

    # Kept for backwards compatibility with your older class:
    # (e.g., callers might inspect DEFAULT_TEMPLATES)
    DEFAULT_TEMPLATES: Dict[str, Dict[str, str]] = {
        "PICOS": {
            "Population": "",
            "Intervention": "",
            "Comparison": "",
            "Outcome": "",
            "Study Design": "",
        },
        "SPIDER": {
            "Sample": "",
            "Phenomenon of Interest": "",
            "Design": "",
            "Evaluation": "",
            "Research Type": "",
        },
        "PECO": {"Population": "", "Exposure": "", "Comparison": "", "Outcome": ""},
        "PIRD": {"Population": "", "Index Test": "", "Reference Standard": "", "Diagnosis": ""},
        "CUSTOM": {
            # dynamic at runtime
        },
    }

    def __init__(
        self,
        template_type: str = "PICOS",
        custom_fields: Optional[List[str]] = None,
        initial_inclusion: Optional[Dict[str, str]] = None,
        initial_exclusion: Optional[Dict[str, str]] = None,
        selected_elements: Optional[List[str]] = None,
        *,
        lang: str = "en",
        texts_base_dir: Optional[str] = None,
        texts: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.template_type: str = (template_type or "CUSTOM").upper().strip()
        self.custom_fields: List[str] = list(custom_fields or [])
        self.selected_elements: List[str] = list(selected_elements or [])

        # Load i18n texts (YAML overlays) or use provided dict, with safe fallback
        self._texts: Dict[str, Any] = (
            texts if texts is not None else _load_texts(lang=lang, base_dir=texts_base_dir)
        )

        # Resolve field names for this framework
        if self.template_type == "CUSTOM":
            fields = list(self.custom_fields)  # a copy: adding an element must not change the input
        else:
            # Prefer i18n-defined fields, fall back to Python defaults
            path = f"screening.framework_fields.{self.template_type}"
            fields = _texts_get_list(self._texts, path, default=None)
            if not fields:
                fields = list(_DEFAULT_FRAMEWORK_FIELDS.get(self.template_type, []))

        # If unknown framework (or empty), gracefully degrade to CUSTOM fields
        if not fields and self.template_type != "CUSTOM":
            logger.warning(
                "No fields resolved for framework '%s'. Falling back to CUSTOM fields.",
                self.template_type,
            )
            fields = list(self.custom_fields)

        # Build internal state (dicts preserve insertion order in Py3.7+)
        self.fields: List[str] = fields
        self.inclusion: Dict[str, str] = {f: "" for f in self.fields}
        self.exclusion: Dict[str, str] = {f: "" for f in self.fields}

        # Apply optional initial values
        if initial_inclusion:
            for k, v in initial_inclusion.items():
                if k in self.inclusion:
                    self.inclusion[k] = v
        if initial_exclusion:
            for k, v in initial_exclusion.items():
                if k in self.exclusion:
                    self.exclusion[k] = v

        # Validate final template type (same rule as in the predecessor)
        if self.template_type not in {"PICOS", "SPIDER", "PECO", "PIRD", "CUSTOM"}:
            raise ValueError(f"Invalid template type: {self.template_type}")

    # ─────────────────────────── mutation API ────────────────────────────

    def update_inclusion(self, field: str, value: Optional[str]) -> None:
        """Set inclusion value for an existing field (raises KeyError if unknown)."""
        if field not in self.inclusion:
            raise KeyError(f"Field '{field}' not found in inclusion criteria.")
        self.inclusion[field] = (value or "").strip()

    def update_exclusion(self, field: str, value: Optional[str]) -> None:
        """Set exclusion value for an existing field (raises KeyError if unknown)."""
        if field not in self.exclusion:
            raise KeyError(f"Field '{field}' not found in exclusion criteria.")
        self.exclusion[field] = (value or "").strip()

    def add_custom_element(self, element_name: str) -> None:
        """
        Add a new custom element to both inclusion and exclusion dicts.
        Mainly for backward compatibility with the API of the predecessor.
        """
        if element_name not in self.inclusion:
            self.inclusion[element_name] = ""
            self.exclusion[element_name] = ""
            if element_name not in self.fields:
                self.fields.append(element_name)  # the prompt is built from ``fields``
            if element_name not in self.selected_elements:
                self.selected_elements.append(element_name)

    def remove_custom_element(self, element_name: str) -> None:
        """Remove an existing custom element from both dicts (and selected_elements)."""
        if element_name in self.inclusion:
            del self.inclusion[element_name]
        if element_name in self.exclusion:
            del self.exclusion[element_name]
        if element_name in self.fields:
            self.fields.remove(element_name)
        if element_name in self.selected_elements:
            self.selected_elements.remove(element_name)

    # ─────────────────────────── accessors ───────────────────────────────

    def get_fields(self) -> List[str]:
        """Return the ordered list of fields for the current framework."""
        return list(self.fields)

    def is_complete(self) -> bool:
        """
        Return True if all inclusion fields are non-empty (same logic as the predecessor).
        """
        return all(isinstance(v, str) and bool(v.strip()) for v in self.inclusion.values())

    def as_dict(self) -> Dict[str, Any]:
        """Return a JSON-serializable representation of the template."""
        return {
            "template_type": self.template_type,
            "inclusion": dict(self.inclusion),
            "exclusion": dict(self.exclusion),
            "selected_elements": list(self.selected_elements),
        }

    @classmethod
    def available_templates(cls) -> Dict[str, Dict[str, str]]:
        """
        Return a copy of the available templates (backwards-compatible helper).
        """
        return {k: dict(v) for k, v in cls.DEFAULT_TEMPLATES.items()}

    # ─────────────────────────── export helpers ──────────────────────────

    def to_prompt_string(self) -> str:
        """
        Build a readable text block (for LLM prompts/logs) using i18n labels if available.

        i18n keys consulted (optional):
            - criteria.prompt.header
            - criteria.prompt.framework_label
            - criteria.prompt.inclusion_header
            - criteria.prompt.exclusion_header
            - criteria.prompt.field_separator
            - criteria.prompt.empty_value
        """
        header = _texts_get_str(
            self._texts, "criteria.prompt.header", _DEFAULT_PROMPT_TEXTS["header"]
        )
        framework_label = _texts_get_str(
            self._texts, "criteria.prompt.framework_label", _DEFAULT_PROMPT_TEXTS["framework_label"]
        )
        inc_header = _texts_get_str(
            self._texts,
            "criteria.prompt.inclusion_header",
            _DEFAULT_PROMPT_TEXTS["inclusion_header"],
        )
        exc_header = _texts_get_str(
            self._texts,
            "criteria.prompt.exclusion_header",
            _DEFAULT_PROMPT_TEXTS["exclusion_header"],
        )
        field_sep = (
            _texts_get_str(
                self._texts,
                "criteria.prompt.field_separator",
                _DEFAULT_PROMPT_TEXTS["field_separator"],
            )
            or ""
        )
        empty_value = _texts_get_str(
            self._texts, "criteria.prompt.empty_value", _DEFAULT_PROMPT_TEXTS["empty_value"]
        )

        lines: List[str] = []
        if header:
            lines.append(header.strip())
        lines.append(f"{framework_label}: {self.template_type}")

        for fld in self.fields:
            if field_sep:
                lines.append(field_sep)

            inc_val = (self.inclusion.get(fld) or "").strip() or empty_value
            exc_val = (self.exclusion.get(fld) or "").strip() or empty_value

            lines.append(f"{fld}:")
            lines.append(f"  {inc_header}: {inc_val}")
            lines.append(f"  {exc_header}: {exc_val}")

        return "\n".join(lines)


# ───────────────────────── manual smoke test ───────────────────────────
if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO)

    # 1) PICOS with defaults/i18n
    c1 = CriteriaTemplate("PICOS", lang="en")
    c1.update_inclusion("Population", "children aged 6–16 with ADHD")
    c1.update_exclusion("Study Design", "case reports")
    print("\n--- PICOS ---\n", c1.to_prompt_string())

    # 2) CUSTOM fields
    c2 = CriteriaTemplate("CUSTOM", custom_fields=["Population", "Outcome"])
    c2.update_inclusion("Population", "school-aged children")
    print("\n--- CUSTOM ---\n", c2.to_prompt_string())
