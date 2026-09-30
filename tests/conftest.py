"""Shared pytest setup: make the tests independent of the machine they run on.

Typer switches its rich output to "forced terminal" (ANSI colour codes, even when piped) when
``GITHUB_ACTIONS``, ``FORCE_COLOR`` or ``PY_COLORS`` is set. That is exactly the situation on the
CI runners, and it broke every test that reads ``--help`` output: the whole CI failed while the
same tests passed on a developer machine. Tests must see the same plain text everywhere.
"""

from __future__ import annotations

import pytest
import typer.rich_utils


@pytest.fixture(autouse=True)
def plain_terminal_output(monkeypatch: pytest.MonkeyPatch) -> None:
    """Never force colour codes into captured CLI output, whatever the environment says."""
    monkeypatch.setattr(typer.rich_utils, "FORCE_TERMINAL", False)
