"""Print one chapter (or list all chapters) of docs/PROJEKTPLAN.md.

Usage:
    python scripts/plan_chapter.py            # list chapters with line numbers
    python scripts/plan_chapter.py 25         # print chapter 25 (including its sub-sections)
    python scripts/plan_chapter.py 25.2       # print only section 25.2

The plan is ~250 KB; agents should read single chapters instead of the whole file.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PLAN = Path(__file__).resolve().parents[1] / "docs" / "PROJEKTPLAN.md"
HEADING = re.compile(r"^(#{2,3}) (\d+(?:\.\d+)?)\.? (.*)$")


def load() -> list[str]:
    return PLAN.read_text(encoding="utf-8").splitlines()


def list_chapters(lines: list[str]) -> None:
    for number, line in enumerate(lines, start=1):
        match = HEADING.match(line)
        if match and match.group(1) == "##":
            print(f"{number:>5}  {match.group(2):>3}  {match.group(3)}")


def print_section(lines: list[str], wanted: str) -> None:
    start = None
    level = 0
    for index, line in enumerate(lines):
        match = HEADING.match(line)
        if start is None:
            if match and match.group(2) == wanted:
                start, level = index, len(match.group(1))
        elif match and len(match.group(1)) <= level:
            print("\n".join(lines[start:index]))
            return
        elif line.startswith("# TEIL") and start is not None:
            print("\n".join(lines[start:index]))
            return
    if start is None:
        sys.exit(f"Section {wanted!r} not found")
    print("\n".join(lines[start:]))


def main() -> None:
    # Windows consoles default to cp1252; the plan contains arrows and umlauts outside cp1252.
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    lines = load()
    if len(sys.argv) < 2:
        list_chapters(lines)
    else:
        print_section(lines, sys.argv[1])


if __name__ == "__main__":
    main()
