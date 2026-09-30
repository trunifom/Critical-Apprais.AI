"""Run the quality gates in the order the CI runs them and stop at the first failure.

Usage (from the project folder, with the virtual environment active or via its python)::

    python scripts/qa.py            # lint, format check, types, all tests
    python scripts/qa.py --fast     # same, with a fixed hypothesis seed; stops at the first failure
    python scripts/qa.py --fix      # first let ruff repair and format what it can, then the gates
    python scripts/qa.py --cov      # also measure the test coverage (needs the dev extra)
    python scripts/qa.py --ci       # same environment switches as GitHub Actions (plain output)

Each step prints its command; the exit code is that of the first step that failed, so the script
can be used as a git hook or in a scheduled job. Nothing here changes the code except ``--fix``.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable
FORMAT_PATHS = ["src", "tests", "scripts"]  # docs/*.md are not formatted by ruff


def steps(*, fast: bool, fix: bool, cov: bool = False) -> list[tuple[str, list[str]]]:
    """The commands to run, in order."""
    plan: list[tuple[str, list[str]]] = []
    if fix:
        plan.append(("ruff fix", [PYTHON, "-m", "ruff", "check", "--fix", "."]))
        plan.append(("ruff format", [PYTHON, "-m", "ruff", "format", *FORMAT_PATHS]))
    plan += [
        ("lint", [PYTHON, "-m", "ruff", "check", "."]),
        ("format", [PYTHON, "-m", "ruff", "format", "--check", *FORMAT_PATHS]),
        ("types", [PYTHON, "-m", "mypy", "src"]),
    ]
    pytest = [PYTHON, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-m", "not live"]
    if fast:
        pytest += ["--hypothesis-seed=0", "-x"]
    if cov:  # coverage is a development tool: only measured when asked for
        pytest += ["--cov=crapai", "--cov-branch", "--cov-report=term-missing:skip-covered"]
    plan.append(("tests", pytest))
    return plan


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "--fast", action="store_true", help="fixed hypothesis seed, stop at first failure"
    )
    parser.add_argument(
        "--fix", action="store_true", help="let ruff fix and format before the gates"
    )
    parser.add_argument("--cov", action="store_true", help="also measure the test coverage")
    parser.add_argument("--ci", action="store_true", help="use the environment of GitHub Actions")
    args = parser.parse_args(argv)
    env = dict(os.environ)
    if args.ci:
        env.update({"GITHUB_ACTIONS": "true", "CI": "true", "FORCE_COLOR": "1"})
    for name, command in steps(fast=args.fast, fix=args.fix, cov=args.cov):
        print(f"\n== {name}: {' '.join(command[1:])}", flush=True)
        started = time.monotonic()
        code = subprocess.run(command, cwd=ROOT, env=env, check=False).returncode  # noqa: S603
        result = "ok" if code == 0 else f"FAILED ({code})"
        print(f"-- {name}: {result} in {time.monotonic() - started:.1f} s")
        if code != 0:
            return code
    print("\nAll gates passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
