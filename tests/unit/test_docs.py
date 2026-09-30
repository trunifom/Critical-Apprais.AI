"""The documentation must stay consistent with the code (user manual, developer docs, README)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from crapai import cli
from crapai.cli import app
from crapai.i18n.required import ERROR_CODES
from crapai.io.records_store import RECORD_COLUMNS

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"


ANSI = re.compile(r"\[[0-9;?]*[A-Za-z]")


def plain(text: str) -> str:
    """Remove ANSI colour codes (rich adds them when a terminal is forced, as on CI runners)."""
    return ANSI.sub("", text)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


MANUAL = read(DOCS / "BENUTZERHANDBUCH.md")
DEVDOC = read(DOCS / "ENTWICKLERDOKUMENTATION.md")
ARCH = read(DOCS / "ARCHITEKTUR.md")
README = read(ROOT / "README.md")


def test_documentation_set_exists_and_is_linked_from_the_readme() -> None:
    for name in (
        "docs/BENUTZERHANDBUCH.md",
        "docs/ENTWICKLERDOKUMENTATION.md",
        "docs/ARCHITEKTUR.md",
        "docs/UMSETZUNGSPLAN_UND_FORTSCHRITT.md",
        "CHANGELOG.md",
    ):
        assert (ROOT / name).is_file(), name
        assert name in README, f"{name} is not listed in README.md"


def test_paths_named_in_backticks_in_the_readme_table_exist() -> None:
    table = README.split("## Dokumentation", 1)[1].split("## Aufbau", 1)[0]
    for path in re.findall(r"`([\w./-]+\.md|docs/adr/)`", table):
        assert (ROOT / path).exists(), path


COMMANDS = ("init", "import", "status", "dedup", "check")


@pytest.mark.parametrize("command", COMMANDS)
def test_every_cli_option_is_documented_in_the_manual(command: str) -> None:
    result = CliRunner().invoke(app, [command, "--help"], terminal_width=200)
    assert result.exit_code == 0
    options = set(re.findall(r"--[a-z][a-z-]*", plain(result.output))) - {"--help"}
    assert options, command
    for option in options:
        assert option in MANUAL, f"{option} of 'crapai {command}' is missing in BENUTZERHANDBUCH.md"


def test_manual_does_not_document_options_the_cli_lacks() -> None:
    known: set[str] = {"--version"}
    for command in COMMANDS:
        output = CliRunner().invoke(app, [command, "--help"], terminal_width=200).output
        known |= set(re.findall(r"--[a-z][a-z-]*", plain(output)))
    mentioned = set(re.findall(r"`(--[a-z][a-z-]*)", MANUAL))
    assert mentioned <= known | {"--force"}, sorted(mentioned - known)


def test_error_codes_in_the_manual_have_texts_in_both_languages() -> None:
    codes = set(re.findall(r"\bE\d{3}\b", MANUAL))
    assert codes, "the manual should list error codes"
    en = yaml.safe_load(read(ROOT / "src/crapai/i18n/texts/en.yaml"))["errors"]
    de = yaml.safe_load(read(ROOT / "src/crapai/i18n/texts/de.yaml"))["errors"]
    for code in codes:
        assert code in ERROR_CODES and code in en and code in de, code


def test_exit_codes_in_the_manual_match_the_cli() -> None:
    assert (cli.EXIT_OK, cli.EXIT_USER_ERROR, cli.EXIT_SYSTEM_ERROR, cli.EXIT_WARNINGS) == (
        0,
        1,
        2,
        4,
    )
    table = MANUAL.split("| Rückgabecode | Bedeutung |", 1)[1].split("\n\n", 1)[0]
    assert re.findall(r"^\| (\d) \|", table, flags=re.MULTILINE) == ["0", "1", "2", "4"]


def test_developer_doc_lists_exactly_the_records_columns() -> None:
    block = DEVDOC.split("### 4.1", 1)[1].split("* `source_format`", 1)[0]
    listed = re.findall(r"\b[a-z_]+\b", block.split("\n\n", 1)[1].split("\n\n", 1)[0])
    assert tuple(listed) == RECORD_COLUMNS


def test_architecture_names_every_module_that_exists() -> None:
    package = ROOT / "src" / "crapai"
    for path in sorted(package.rglob("*.py")):
        relative = path.relative_to(package)
        if path.name == "__init__.py" or relative.parts[0] in {"cost", "criteria", "legacy.py"}:
            continue
        dotted = ".".join(relative.with_suffix("").parts)
        if dotted in {"enums", "branding", "i18n.required", "i18n.loader", "i18n.texts.fallback"}:
            continue
        leaf = dotted.split(".")[-1]
        assert dotted in ARCH or f"`{leaf}`" in ARCH or leaf in ARCH, (
            f"{dotted} is not in ARCHITEKTUR.md"
        )


def test_product_is_named_correctly_in_the_user_facing_documents() -> None:
    for name, text in (("README", README), ("manual", MANUAL), ("architecture", ARCH)):
        assert "Critical Apprais.AI" in text, name
        assert "Critical Appraisal" not in text and "CriticalApprais" not in text, name
    assert "früher als Prototyp" in MANUAL  # SARA appears only as the predecessor there


def test_changelog_mentions_the_milestone_and_known_limits() -> None:
    changelog = read(ROOT / "CHANGELOG.md")
    for needle in ("T-M1-05", "T-M1-11", "T-M1-12", "Bekannte Einschränkungen", "E401"):
        assert needle in changelog, needle


def test_help_parsing_survives_forced_terminal_colours(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression test for the CI failure: GitHub runners force ANSI colours into --help output.

    The autouse fixture in conftest.py normally prevents it; here the colours are forced on
    purpose to prove that the option check itself is robust as well.
    """
    import typer.rich_utils

    monkeypatch.setattr(typer.rich_utils, "FORCE_TERMINAL", True)
    result = CliRunner().invoke(app, ["import", "--help"], terminal_width=200)
    assert result.exit_code == 0
    assert "\x1b[" in result.output, "colours were expected to be forced for this test"
    options = set(re.findall(r"--[a-z][a-z-]*", plain(result.output)))
    assert {"--label", "--map", "--force", "--json"} <= options
    assert "--label" not in result.output  # the raw text is broken up by colour codes
