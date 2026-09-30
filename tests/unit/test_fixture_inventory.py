"""Verify tests/data against EXPECTED.json (independent oracle, see scripts/build_expected.py)."""

import json
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = json.loads((ROOT / "data" / "EXPECTED.json").read_text(encoding="utf-8"))
FILES = {k: v for k, v in EXPECTED.items() if not k.startswith("_")}


@pytest.mark.parametrize("name", sorted(FILES))
def test_file_exists_with_expected_size(name: str) -> None:
    path = ROOT / name
    if name.startswith("data_large/") and not path.exists():
        pytest.skip("large fixture not present")
    assert path.stat().st_size == FILES[name]["bytes"]


def test_example_db_files_declare_their_duplicates() -> None:
    """Duplicate counts in file names (nr2: 3, nr3: 2) match the DOI-based count."""
    nr2 = FILES["data/example_db_nr2_total-10_duplicates-3.ris"]
    nr3 = FILES["data/example_db_nr3_total-8_duplicates-2.ris"]
    assert nr2["records"] - nr2["unique_doi"] == 3
    assert nr3["records"] - nr3["unique_doi"] == 2


def test_example_db_nr1_name_is_inaccurate() -> None:
    """The name says total-15 but the file holds 13 records; tests must use the real number."""
    assert FILES["data/example_db_nr1_total-15_duplicates-0.ris"]["records"] == 13


def test_cross_source_duplicates_of_the_three_example_databases() -> None:
    merged = EXPECTED["_derived/example_db_trio_merged"]
    assert (merged["records_total"], merged["unique_doi"], merged["duplicates_by_doi"]) == (
        31,
        13,
        18,
    )


def test_pubmed_ris_is_really_an_nbib() -> None:
    a = (ROOT / "data" / "pubmed-adhd-set.ris").read_bytes()
    b = (ROOT / "data" / "pubmed-adhd-set.nbib").read_bytes()
    assert a == b
    assert a.startswith(b"PMID-")


def test_zip_contains_macosx_ballast() -> None:
    path = ROOT / "data_large" / "test.zip"
    if not path.exists():
        pytest.skip("large fixture not present")
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
    assert sum(n.startswith("__MACOSX/") for n in names) == 6
    assert len(names) == 12
