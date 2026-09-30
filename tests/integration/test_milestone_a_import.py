"""Milestone A ("import is in place"): every fixture imports through the real CLI and the
numbers equal the independent oracle in tests/data/EXPECTED.json (plan chapter 21, kickoff 9.1)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from saralocal.cli import app
from saralocal.io.records_store import read_records

DATA = Path(__file__).resolve().parents[1] / "data"
EXPECTED = json.loads((DATA / "EXPECTED.json").read_text(encoding="utf-8"))
BIBLIO = sorted(
    name.removeprefix("data/")
    for name, info in EXPECTED.items()
    if name.startswith("data/") and info.get("kind") in {"ris", "nbib", "bibtex"}
)
runner = CliRunner()


def cli(*args: object) -> int:
    return runner.invoke(app, [str(a) for a in args], catch_exceptions=False).exit_code


@pytest.mark.parametrize("name", BIBLIO)
def test_fixture_imports_with_the_oracle_numbers(name: str, tmp_path: Path) -> None:
    project = tmp_path / "p"
    assert cli("init", project, "--from-template", "demo", "--lang", "en") == 0
    exit_code = cli("import", project, DATA / name, "--label", "X", "--lang", "en")
    assert exit_code in (0, 4)  # 4 = warnings, e.g. fixtures without abstracts
    records = read_records(project / "data" / "records.csv")
    info = EXPECTED[f"data/{name}"]
    assert len(records) == info["records"]
    if "abstracts" in info:
        assert sum(r.has_abstract for r in records) == info["abstracts"]
    if "doi_count" in info:
        dois = [r.doi for r in records if r.doi]
        invalid = sum(1 for r in records if "doi_invalid" in r.extra_json)
        assert len(dois) + invalid == info["doi_count"]
        assert len(set(dois)) == info["unique_doi"] or invalid > 0
    assert all(r.title or r.abstract or r.exclusion_reason == "EMPTY_RECORD" for r in records)
    assert len({r.study_uid for r in records}) == len(records)
    assert cli("status", project, "--lang", "en") == 0


def test_the_three_example_databases_together(tmp_path: Path) -> None:
    """31 records, 13 distinct DOIs: the 18 duplicates are still there (marked later, T-M2-01)."""
    oracle = EXPECTED["_derived/example_db_trio_merged"]
    project = tmp_path / "p"
    assert cli("init", project, "--from-template", "demo", "--lang", "en") == 0
    for index, file_name in enumerate(oracle["files"], start=1):
        assert cli("import", project, DATA / file_name, "--label", f"Db{index}") in (0, 4)
    records = read_records(project / "data" / "records.csv")
    assert len(records) == oracle["records_total"]
    assert len({r.doi for r in records if r.doi}) == oracle["unique_doi"]
    assert not any(r.is_duplicate for r in records)  # nothing is deleted or flagged on import
    assert {r.source_label for r in records} == {"Db1", "Db2", "Db3"}


def test_zotero_ris_and_bib_agree_on_the_number_of_records(tmp_path: Path) -> None:
    project = tmp_path / "p"
    cli("init", project, "--from-template", "demo")
    cli("import", project, DATA / "pubmed_adhd_converted-zotero.ris", "--label", "RIS")
    cli("import", project, DATA / "pubmed_adhd_converted-zotero.bib", "--label", "BIB")
    records = read_records(project / "data" / "records.csv")
    counts = {"RIS": 0, "BIB": 0}
    for record in records:
        counts[record.source_label] += 1
    assert counts == {"RIS": 706, "BIB": 706}
