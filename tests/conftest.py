"""Shared pytest setup: make the tests independent of the machine they run on.

Typer switches its rich output to "forced terminal" (ANSI colour codes, even when piped) when
``GITHUB_ACTIONS``, ``FORCE_COLOR`` or ``PY_COLORS`` is set. That is exactly the situation on the
CI runners, and it broke every test that reads ``--help`` output: the whole CI failed while the
same tests passed on a developer machine. Tests must see the same plain text everywhere.
"""

from __future__ import annotations

import pytest
import typer.rich_utils

from crapai.project import atomic, lock


@pytest.fixture(autouse=True)
def plain_terminal_output(monkeypatch: pytest.MonkeyPatch) -> None:
    """Never force colour codes into captured CLI output, whatever the environment says."""
    monkeypatch.setattr(typer.rich_utils, "FORCE_TERMINAL", False)


@pytest.fixture(autouse=True)
def fast_storage(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip disk flushes and retry pauses: they protect real disks and only slow the tests.

    Tests that check the retry behaviour pass their own ``sleep``/``delay_s`` or set these
    constants again.
    """
    monkeypatch.setattr(atomic, "FSYNC", False)
    monkeypatch.setattr(atomic, "DEFAULT_DELAY_S", 0.0)
    monkeypatch.setattr(lock, "READ_RETRY_DELAY_S", 0.0)


@pytest.fixture(autouse=True)
def isolated_home(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep the user's real home (recent projects, user config) out of every test."""
    home = tmp_path_factory.mktemp("home")
    monkeypatch.setenv("USERPROFILE", str(home))  # Path.home() on Windows
    monkeypatch.setenv("HOME", str(home))  # Path.home() elsewhere
