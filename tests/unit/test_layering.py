"""Architecture contract (plan chapter 28.2).

The core imports no GUI framework, CLI framework or LLM SDK.

The check parses the source with ``ast`` so it needs no extra dependency (import-linter would be a
new dependency and needs the project lead's approval, see AGENTS.md section 7).
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "crapai"

# Third-party packages the core must never import (GUI, CLI, LLM SDKs).
FORBIDDEN_THIRD_PARTY = frozenset(
    {"streamlit", "streamlit_aggrid", "st_aggrid", "typer", "openai", "anthropic"}
)
# Layers above or beside the core. Core modules must not import them (arrows point downwards).
UPPER_LAYERS = frozenset({"cli", "ui", "services", "adapters"})
# Top-level sub-packages that are allowed to depend on the forbidden packages.
NON_CORE = UPPER_LAYERS


def imported_modules(source: str) -> set[str]:
    """Return the dotted names of all modules imported in ``source`` (lazy imports included)."""
    modules: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules.add(node.module)
    return modules


def layer_violations(root: Path) -> list[str]:
    """List ``file: module`` pairs where a core module breaks the layering rules."""
    violations: list[str] = []
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root)
        # A layer is a package (cli/) or a module (cli.py); compare without the suffix.
        if relative.parts[0].removesuffix(".py") in NON_CORE:
            continue
        for module in sorted(imported_modules(path.read_text(encoding="utf-8"))):
            parts = module.split(".")
            forbidden = parts[0] in FORBIDDEN_THIRD_PARTY
            upward = parts[0] == "crapai" and len(parts) > 1 and parts[1] in UPPER_LAYERS
            if forbidden or upward:
                violations.append(f"{relative.as_posix()}: {module}")
    return violations


def test_core_has_no_gui_cli_or_llm_sdk_imports() -> None:
    assert layer_violations(SRC) == []


def test_detector_flags_forbidden_and_upward_imports(tmp_path: Path) -> None:
    """The check must fail when the rules are broken, otherwise it protects nothing."""
    (tmp_path / "cli").mkdir()
    # Allowed: the cli layer is not core.
    (tmp_path / "cli" / "app.py").write_text("import typer\n", encoding="utf-8")
    (tmp_path / "engine.py").write_text(
        "import streamlit as st\nfrom crapai.cli import app\n", encoding="utf-8"
    )
    (tmp_path / "provider.py").write_text(
        "def build():\n    from openai import OpenAI\n    return OpenAI\n", encoding="utf-8"
    )
    (tmp_path / "clean.py").write_text("import json\nimport pandas\n", encoding="utf-8")

    assert layer_violations(tmp_path) == [
        "engine.py: crapai.cli",
        "engine.py: streamlit",
        "provider.py: openai",
    ]
