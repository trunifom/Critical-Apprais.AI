"""English and German texts must match key for key (task T-M1-12, plan chapter 27.7)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from crapai.i18n import I18n
from crapai.i18n.required import ERROR_CODES, ERROR_PARTS, required_keys

TEXTS = Path(__file__).resolve().parents[2] / "src" / "crapai" / "i18n" / "texts"
PLACEHOLDER = re.compile(r"\{(\w+)\}")


def leaves(node: Any, prefix: str = "") -> dict[str, Any]:
    if isinstance(node, dict):
        result: dict[str, Any] = {}
        for key, value in node.items():
            result.update(leaves(value, f"{prefix}{key}."))
        return result
    return {prefix.rstrip("."): node}


def load(lang: str) -> dict[str, Any]:
    return leaves(yaml.safe_load((TEXTS / f"{lang}.yaml").read_text(encoding="utf-8")))


EN, DE = load("en"), load("de")


def strings(value: Any) -> list[str]:
    return [str(v) for v in value] if isinstance(value, list) else [str(value)]


def test_both_files_have_exactly_the_same_keys() -> None:
    assert sorted(set(EN) - set(DE)) == [], "missing in de.yaml"
    assert sorted(set(DE) - set(EN)) == [], "missing in en.yaml"


def test_same_placeholders_and_same_list_lengths() -> None:
    for key, english in EN.items():
        german = DE[key]
        assert isinstance(english, list) == isinstance(german, list), key
        if isinstance(english, list):
            assert len(english) == len(german), key
        found_en = {p for s in strings(english) for p in PLACEHOLDER.findall(s)}
        found_de = {p for s in strings(german) for p in PLACEHOLDER.findall(s)}
        assert found_en == found_de, key


def test_no_empty_texts() -> None:
    for name, texts in (("en", EN), ("de", DE)):
        for key, value in texts.items():
            assert all(part.strip() for part in strings(value)), (name, key)


def test_every_required_key_exists_in_both_languages() -> None:
    keys = list(required_keys())
    assert len(keys) == len(set(keys))
    for lang in ("en", "de"):
        i18n = I18n()
        i18n.load(lang)
        assert i18n.validate(keys) == [], lang


def test_required_keys_exist_in_the_yaml_files_themselves() -> None:
    """Not just via the Python fallback: the YAML must carry them."""
    for key in required_keys():
        assert key in EN and key in DE, key


def test_error_texts_follow_what_why_what_to_do() -> None:
    for code in ERROR_CODES:
        for part in ERROR_PARTS:
            for texts in (EN, DE):
                text = texts[f"errors.{code}.{part}"]
                assert isinstance(text, str) and text.strip().endswith((".", "…")), (code, part)
    catalogue = {key.split(".")[1] for key in EN if key.startswith("errors.")}
    assert catalogue == set(ERROR_CODES)


def test_german_uses_swiss_spelling_and_formal_address() -> None:
    joined = "\n".join(s for v in DE.values() for s in strings(v))
    assert "ß" not in joined
    for informal in (" dein ", " deine ", " du ", " dir ", " dich "):
        assert informal not in joined.lower(), informal.strip()


def test_no_user_text_calls_the_product_sara_or_promises_email() -> None:
    for name, texts in (("en", EN), ("de", DE)):
        for key, value in texts.items():
            for text in strings(value):
                assert "SARA" not in text, (name, key)
    assert "no e-mail is sent" in EN["notifications.background_info"]
    assert "keine E-Mail" in DE["notifications.background_info"]


def test_full_text_is_not_offered_in_version_1() -> None:
    assert EN["sections.screening.review_mode.options"] == ["Abstract"]
    assert DE["sections.screening.review_mode.options"] == ["Abstract"]
    assert not [k for k in EN if k.startswith("sections.upload.fulltext")]


@pytest.mark.parametrize("lang", ["en", "de"])
def test_formatting_with_real_values_works(lang: str) -> None:
    i18n = I18n()
    i18n.load(lang)
    assert "2" in i18n.tf("data.low_abstracts", percent=2)
    assert "Run-1" in i18n.tf("notifications.review_started", file_id="Run-1")
    assert "x.ris" in i18n.tf("sections.upload.abstract.database_field.label", filename="x.ris")
