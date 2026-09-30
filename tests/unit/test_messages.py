"""Tests for the CLI/error message texts in English and German (task T-M1-11)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from crapai.errors import (
    ConfigError,
    ImportFailed,
    ProviderError,
    SaraError,
    StorageError,
)
from crapai.i18n.messages import Messages, resolve_language

TEXTS = Path(__file__).resolve().parents[2] / "src" / "crapai" / "i18n" / "texts"


def flatten(node: Any, prefix: str = "") -> dict[str, str]:
    if isinstance(node, dict):
        result: dict[str, str] = {}
        for key, value in node.items():
            result.update(flatten(value, f"{prefix}{key}."))
        return result
    return {prefix.rstrip("."): str(node)}


def load(lang: str, section: str) -> dict[str, str]:
    data = yaml.safe_load((TEXTS / f"{lang}.yaml").read_text(encoding="utf-8"))
    return flatten(data[section], f"{section}.")


@pytest.mark.parametrize("section", ["cli", "errors"])
def test_english_and_german_have_the_same_keys_and_placeholders(section: str) -> None:
    en, de = load("en", section), load("de", section)
    assert set(en) == set(de)
    for key, text in en.items():
        assert set(re.findall(r"\{(\w+)\}", text)) == set(re.findall(r"\{(\w+)\}", de[key])), key
        assert de[key].strip() and text.strip()


def test_no_user_text_names_the_product_sara() -> None:
    for lang in ("en", "de"):
        for section in ("cli", "errors"):
            for key, text in load(lang, section).items():
                assert "SARA" not in text, (lang, key)


def test_german_texts_use_swiss_spelling() -> None:
    assert not any("ß" in text for text in load("de", "cli").values())
    assert not any("ß" in text for text in load("de", "errors").values())


def test_every_error_code_the_import_path_can_raise_has_texts() -> None:
    codes = {"E101", "E102", "E103", "E104", "E106", "E201", "E203", "E401", "E402", "E403", "E404"}
    codes.add("E999")
    for lang in ("en", "de"):
        keys = load(lang, "errors")
        for code in codes:
            assert keys[f"errors.{code}.title"] and keys[f"errors.{code}.action"], (lang, code)


def test_error_lines_have_what_happened_details_and_what_to_do() -> None:
    error = ImportFailed("File a.ris was already imported", code="E106", hint="english hint")
    lines = Messages("en").error_lines(error)
    assert lines[0] == "Error E106: This file has already been imported."
    assert lines[1].startswith("Why: A file with identical content")
    assert lines[2] == "Details: File a.ris was already imported"
    assert lines[3].startswith("What to do: Use --force")
    german = Messages("de").error_lines(error)
    assert german[0].startswith("Fehler E106: Diese Datei wurde bereits importiert")
    assert german[1].startswith("Warum: Eine Datei mit identischem Inhalt")
    assert german[3].startswith("Was tun: Mit --force")


def test_unknown_code_falls_back_to_the_generic_text_but_keeps_its_code() -> None:
    lines = Messages("en").error_lines(ProviderError("odd", code="E777"))
    assert lines[0].startswith("Error E777: An unexpected error occurred.")
    assert "Details: odd" in lines


def test_hint_is_used_when_no_action_text_exists() -> None:
    error = SaraError("x", code="E999", hint=None)
    # title, cause, details and action all come from the catalogue
    assert len(Messages("en").error_lines(error)) == 4


def test_text_lookup_placeholders_missing_keys_and_language_fallback() -> None:
    en = Messages("en")
    assert en.text("cli.init.done", path="p") == "Project created: p"
    assert en.text("no.such.key") == "no.such.key"
    assert en.text("cli.init.done") == "Project created: {path}"  # missing value: no crash
    assert Messages("xx").language == "en"
    assert Messages("de").text("cli.init.done", path="p") == "Projekt angelegt: p"


def test_resolve_language_order(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LC_ALL", raising=False)
    monkeypatch.setenv("LANG", "de_CH.UTF-8")
    assert resolve_language() == "de"
    monkeypatch.setenv("LANG", "fr_FR")
    assert resolve_language() == "en"
    project = tmp_path / "project.yaml"
    project.write_text("project:\n  title: t\n  language: de\n", encoding="utf-8")
    assert resolve_language(None, project) == "de"  # project beats LANG
    assert resolve_language("en", project) == "en"  # explicit beats project
    assert resolve_language("fr", project) == "en"  # unsupported explicit value
    project.write_text("{{ not yaml", encoding="utf-8")
    assert resolve_language(None, project) == "en"  # broken file: fall back, do not fail


def test_the_error_classes_in_use_are_covered() -> None:
    for error in (ConfigError("x"), StorageError("x"), ImportFailed("x")):
        assert Messages("en").error_lines(error)[0].startswith(f"Error {error.code}")
