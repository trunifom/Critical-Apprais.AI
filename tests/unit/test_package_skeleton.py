"""Package skeleton of task T-M1-01: every sub-package imports and carries a docstring."""

from __future__ import annotations

import importlib

import pytest

SUBPACKAGES = [
    "project",
    "io",
    "io.readers",
    "prisma",
    "screening",
    "llm",
    "prompts",
    "stats",
    "services",
    # Already ported earlier; the skeleton must not break them.
    "criteria",
    "cost",
    "i18n",
]


@pytest.mark.parametrize("name", SUBPACKAGES)
def test_subpackage_imports_and_has_docstring(name: str) -> None:
    module = importlib.import_module(f"saralocal.{name}")
    assert module.__doc__ and module.__doc__.strip(), f"saralocal.{name} needs a docstring"
