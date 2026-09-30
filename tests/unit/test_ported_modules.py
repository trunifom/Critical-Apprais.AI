"""Additional tests for modules ported from the predecessor (criteria template, legacy reader).

The golden tests reproduce the archived reports; these tests cover the edge behaviour that the
reports never exercise: mutation API, defaults when the text files are unavailable, and the
error paths of the legacy reader.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd
import pytest

from crapai import legacy
from crapai.criteria import template as template_module
from crapai.criteria.template import CriteriaTemplate

# --- criteria template -------------------------------------------------------------------------


def test_custom_elements_can_be_added_and_removed() -> None:
    criteria = CriteriaTemplate("CUSTOM", custom_fields=["Topic"])
    criteria.add_custom_element("Setting")
    criteria.add_custom_element("Setting")  # adding twice changes nothing
    assert "Setting" in criteria.inclusion and "Setting" in criteria.exclusion
    assert criteria.selected_elements.count("Setting") == 1
    criteria.remove_custom_element("Setting")
    criteria.remove_custom_element("Setting")  # removing twice is harmless
    assert "Setting" not in criteria.inclusion and "Setting" not in criteria.exclusion
    assert "Setting" not in criteria.selected_elements


def test_exclusion_updates_strip_and_reject_unknown_fields() -> None:
    criteria = CriteriaTemplate("PICOS")
    criteria.update_exclusion("Population", "  children  ")
    criteria.update_exclusion("Outcome", None)
    assert criteria.exclusion["Population"] == "children" and criteria.exclusion["Outcome"] == ""
    with pytest.raises(KeyError):
        criteria.update_exclusion("Nope", "x")
    with pytest.raises(KeyError):
        criteria.update_inclusion("Nope", "x")


def test_completeness_needs_every_inclusion_field() -> None:
    criteria = CriteriaTemplate("PECO")
    assert criteria.is_complete() is False
    for field in criteria.get_fields():
        criteria.update_inclusion(field, "something")
    assert criteria.is_complete() is True
    criteria.update_inclusion("Exposure", "   ")
    assert criteria.is_complete() is False


def test_initial_values_apply_only_to_known_fields() -> None:
    criteria = CriteriaTemplate(
        "PICOS",
        initial_inclusion={"Population": "adults", "Unknown": "ignored"},
        initial_exclusion={"Outcome": "none", "Unknown": "ignored"},
    )
    assert criteria.inclusion["Population"] == "adults" and "Unknown" not in criteria.inclusion
    assert criteria.exclusion["Outcome"] == "none" and "Unknown" not in criteria.exclusion


def test_available_templates_returns_copies() -> None:
    first = CriteriaTemplate.available_templates()
    first["PICOS"]["Population"] = "changed"
    assert CriteriaTemplate.available_templates()["PICOS"]["Population"] != "changed"
    assert set(first) >= {"PICOS", "SPIDER", "PECO", "PIRD"}


def test_pird_uses_the_diagnostic_fields() -> None:
    assert CriteriaTemplate("PIRD").get_fields() == [
        "Population",
        "Index Test",
        "Reference Standard",
        "Diagnosis",
    ]


def test_prompt_block_lists_every_field_with_inclusion_and_exclusion() -> None:
    criteria = CriteriaTemplate("SPIDER")
    criteria.update_inclusion("Sample", "nurses")
    block = criteria.to_prompt_string()
    assert "Screening Criteria" in block and "SPIDER" in block
    assert "Sample:" in block and "nurses" in block
    for field in criteria.get_fields():
        assert f"{field}:" in block


def test_prompt_labels_come_from_the_texts_when_given() -> None:
    texts = {
        "criteria": {
            "prompt": {
                "header": "Kriterien",
                "framework_label": "Rahmenwerk",
                "inclusion_header": "Einschluss",
                "exclusion_header": "Ausschluss",
                "field_separator": "",
                "empty_value": "(leer)",
            }
        }
    }
    block = CriteriaTemplate("PECO", texts=texts).to_prompt_string()
    assert block.splitlines()[:2] == ["Kriterien", "Rahmenwerk: PECO"]
    assert "Einschluss: (leer)" in block and "Ausschluss: (leer)" in block


def test_without_the_text_loader_built_in_defaults_are_used(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    class Broken:
        def __init__(self, *args: object, **kwargs: object) -> None:
            raise RuntimeError("no texts here")

    monkeypatch.setattr("crapai.i18n.I18n", Broken)
    template_module._load_texts.cache_clear()
    try:
        with caplog.at_level(logging.WARNING, logger=template_module.logger.name):
            criteria = CriteriaTemplate("PICOS", lang="zz")
        assert criteria.get_fields()[0] == "Population"
        assert any("i18n not available" in record.message for record in caplog.records)
    finally:
        template_module._load_texts.cache_clear()


def test_text_helpers_handle_missing_and_odd_values() -> None:
    texts = {"a": {"list": ["x", 2], "number": 7, "text": "t", "bad": {"nested": 1}}}
    get_list, get_str = template_module._texts_get_list, template_module._texts_get_str
    assert get_list(texts, "a.list") == ["x", "2"]
    assert get_list(texts, "a.text", default=["d"]) == ["d"]
    assert get_str(texts, "a.number") == "7" and get_str(texts, "a.text") == "t"
    assert get_str(texts, "a.bad", default="fallback") == "fallback"
    assert get_str(texts, "a.missing.deeper") == ""
    assert template_module._deep_get(texts, "a.text.deeper") is None


# --- legacy reader --------------------------------------------------------------------------------


def write_run(path: Path, text: str, encoding: str = "utf-8") -> Path:
    path.write_bytes(text.encode(encoding))
    return path


def test_legacy_run_is_read_in_cp1252_and_utf8(tmp_path: Path) -> None:
    body = "study_uid;title;label\nu1;Größe;1\nu2;Zwei;0\n"
    utf8 = legacy.read_legacy_run(write_run(tmp_path / "a_run-01.csv", body))
    cp = legacy.read_legacy_run(write_run(tmp_path / "b_run-02.csv", body, "cp1252"))
    assert utf8.equals(cp) and list(utf8.columns) == ["study_uid", "label"]
    wide = legacy.read_legacy_run(tmp_path / "a_run-01.csv", ("study_uid", "title"))
    assert wide["title"].tolist() == ["Größe", "Zwei"]


def test_legacy_run_without_the_requested_columns_is_an_error(tmp_path: Path) -> None:
    path = write_run(tmp_path / "x_run-01.csv", "id;other\n1;2\n")
    with pytest.raises(ValueError, match="Cannot read"):
        legacy.read_legacy_run(path)


def test_run_tag_needs_a_run_number() -> None:
    assert legacy.run_tag(Path("20251118-1152_uuid_run-07.csv")) == "run-07"
    with pytest.raises(ValueError, match="No run tag"):
        legacy.run_tag(Path("results.csv"))


def test_load_runs_merges_by_study_uid_and_reports_empty_folders(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        legacy.load_runs(tmp_path)
    write_run(tmp_path / "1_p_run-01.csv", "study_uid;label\nu1;1\nu2;0\n")
    write_run(tmp_path / "2_p_run-02.csv", "study_uid;label\nu2;0\nu3;1\nu4;\n")
    runs = legacy.load_runs(tmp_path)
    assert sorted(runs["study_uid"]) == ["u1", "u2", "u3", "u4"]
    by_uid = runs.set_index("study_uid")
    assert by_uid.loc["u1", "run-01"] == 1 and pd.isna(by_uid.loc["u1", "run-02"])
    assert pd.isna(by_uid.loc["u4", "run-02"])  # an empty label stays empty, never a class


def test_kappa_edge_cases() -> None:
    same = pd.Series([1, 1, 1])
    assert legacy.cohen_kappa(same, same) != legacy.cohen_kappa(same, same)  # NaN: undefined
    assert legacy.cohen_kappa(pd.Series([1, 0, 1, 0]), pd.Series([1, 0, 1, 0])) == 1.0
    assert legacy.cohen_kappa(pd.Series([1, 0, 1, 0]), pd.Series([0, 1, 0, 1])) == -1.0
    with pytest.raises(ValueError):
        legacy.cohen_kappa(pd.Series([1]), pd.Series([1, 0]))
    with pytest.raises(ValueError):
        legacy.cohen_kappa(pd.Series([], dtype=int), pd.Series([], dtype=int))


@pytest.mark.parametrize(
    ("kappa", "label"),
    [
        (float("nan"), "Undefined"),
        (-0.3, "Poor"),
        (0.1, "Slight"),
        (0.3, "Fair"),
        (0.5, "Moderate"),
        (0.7, "Substantial"),
        (0.95, "Almost Perfect"),
        (1.0, "Almost Perfect"),
        (1.5, "Unknown"),
    ],
)
def test_kappa_interpretation_bands(kappa: float, label: str) -> None:
    assert legacy.interpret_kappa(kappa) == label


def test_pairwise_stats_needs_two_runs_and_skips_pairs_without_overlap(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with pytest.raises(ValueError):
        legacy.pairwise_stats(pd.DataFrame({"study_uid": ["a"], "run-01": [1]}))
    runs = pd.DataFrame(
        {
            "study_uid": ["a", "b", "c", "d"],
            "run-01": [1, 0, float("nan"), float("nan")],
            "run-02": [1, 0, 1, float("nan")],
            "run-03": [float("nan"), float("nan"), float("nan"), 1],
        }
    )
    with caplog.at_level(logging.WARNING, logger=legacy.LOGGER.name):
        stats = legacy.pairwise_stats(runs)
    assert list(stats["run1"] + "/" + stats["run2"]) == ["run-01/run-02"]  # others have no overlap
    assert stats.loc[0, "n_overlap"] == 2 and stats.loc[0, "percent_agreement"] == 1.0
    assert any("No overlapping records" in record.message for record in caplog.records)
