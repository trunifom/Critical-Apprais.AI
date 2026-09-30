"""Definition of done, enforced: public API of the new code has docstrings and return types.

Ported predecessor modules keep their original style until a task refactors them (see
pyproject.toml); they are excluded here. Nested helper functions are not part of the public API.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "crapai"
PORTED = {"enums.py", "legacy.py", "fallback.py"}
PORTED_PACKAGES = {"cost", "criteria"}


def modules() -> list[Path]:
    return [
        path
        for path in sorted(SRC.rglob("*.py"))
        if path.name not in PORTED and not PORTED_PACKAGES & set(path.relative_to(SRC).parts)
    ]


def public_defs(tree: ast.Module) -> list[ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef]:
    """Module-level and class-level definitions that do not start with an underscore."""
    functions = (ast.FunctionDef, ast.AsyncFunctionDef)
    found: list[ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            found.append(node)
            found.extend(
                child
                for child in node.body
                if isinstance(child, functions) and not child.name.startswith("_")
            )
        elif isinstance(node, functions) and not node.name.startswith("_"):
            found.append(node)
    return found


@pytest.mark.parametrize("path", modules(), ids=lambda p: p.relative_to(SRC).as_posix())
def test_module_and_public_api_have_docstrings_and_return_types(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    problems: list[str] = []
    if not ast.get_docstring(tree):
        problems.append("module docstring")
    for node in public_defs(tree):
        if not ast.get_docstring(node):
            problems.append(f"docstring of {node.name}")
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.returns is None:
            problems.append(f"return type of {node.name}")
    assert not problems, f"{path.name}: missing " + ", ".join(problems)


def test_the_guard_actually_finds_problems() -> None:
    source = (
        "def public(x):\n    return x\n\n"
        "class Thing:\n    def method(self) -> int:\n        return 1\n"
    )
    tree = ast.parse(source)
    names = [node.name for node in public_defs(tree)]
    assert names == ["public", "Thing", "method"]
    assert not any(ast.get_docstring(node) for node in public_defs(tree))
