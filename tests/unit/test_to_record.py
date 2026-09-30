"""Tests for RawRecord -> Record conversion and the reader-to-CSV chain (task T-M1-10)."""

from __future__ import annotations

import itertools
import json
from pathlib import Path

import pytest

from crapai.io.normalize import ImportContext, to_record, to_records
from crapai.io.readers.base import RawRecord
from crapai.io.readers.bibtex import read_bibtex
from crapai.io.readers.nbib import read_nbib
from crapai.io.readers.ris import read_ris
from crapai.io.readers.tabular import read_table
from crapai.io.records_store import RECORD_COLUMNS, read_records, write_records

DATA = Path(__file__).resolve().parents[2] / "tests" / "data"
EXPECTED = json.loads((DATA / "EXPECTED.json").read_text(encoding="utf-8"))


def context(source_format: str = "ris") -> ImportContext:
    counter = itertools.count(1)
    return ImportContext("Test", "test.ris", source_format, new_uid=lambda: f"uid-{next(counter)}")


def test_basic_conversion_sets_identity_and_flags() -> None:
    raw = RawRecord(
        7,
        {"title": "  A\ttitle\n", "abstract": "Line one\nline two", "year": "2020 Oct"},
        {"ris_C1": "kept"},
        ["note one", "note two"],
    )
    record = to_record(raw, context())
    identity = (record.study_uid, record.source_label, record.source_file)
    assert identity == ("uid-1", "Test", "test.ris")
    assert (record.source_row, record.source_format) == (7, "ris")
    assert record.title == "A title" and record.abstract == "Line one line two"
    assert record.year == 2020 and record.has_abstract is True
    assert record.import_notes == "note one; note two"
    assert record.extra_json == {"ris_C1": "kept"}
    assert record.exclusion_reason == ""


def test_source_format_names_follow_the_csv_contract() -> None:
    names = {
        fmt: to_record(RawRecord(1, {"title": "t"}), context(fmt)).source_format
        for fmt in ("ris", "nbib", "bibtex", "csv", "tsv", "xlsx")
    }
    assert names == {
        "ris": "ris",
        "nbib": "nbib",
        "bibtex": "bib",
        "csv": "csv",
        "tsv": "csv",
        "xlsx": "xlsx",
    }


def test_empty_record_is_marked_not_dropped() -> None:
    record = to_record(RawRecord(1, {"record_type": "journal_article", "authors": "X"}), context())
    assert record.exclusion_reason == "EMPTY_RECORD"
    assert record.exclusion_details == "neither title nor abstract"
    assert record.has_abstract is False and record.authors == "X"
    only_abstract = to_record(RawRecord(2, {"abstract": "text"}), context())
    assert only_abstract.exclusion_reason == ""


def test_doi_is_normalised_and_invalid_doi_is_kept_in_extra() -> None:
    good = to_record(RawRecord(1, {"title": "t", "doi": "https://doi.org/10.1234/ABC"}), context())
    assert good.doi == "10.1234/abc" and "doi_invalid" not in good.extra_json
    bad = to_record(RawRecord(2, {"title": "t", "doi": "see publisher website"}), context())
    assert bad.doi == "" and bad.extra_json["doi_invalid"] == "see publisher website"


def test_unknown_fields_and_types_are_kept_in_extra_json() -> None:
    raw = RawRecord(
        1,
        {"title": "t", "notes": "n", "database_name": "Embase", "record_type": "podcast",
         "year": "n.d.", "publisher": "P"},
    )
    record = to_record(raw, context())
    assert record.record_type == "other"
    assert record.extra_json == {
        "notes": "n",
        "database_name": "Embase",
        "publisher": "P",
        "record_type_raw": "podcast",
    }
    assert record.year is None  # no placeholder year


def test_lists_are_tidied_and_control_characters_removed() -> None:
    fields = {"title": "a\x00b", "authors": "Doe, J;; Doe, J; Roe, R ;", "keywords": "x;x"}
    record = to_record(RawRecord(1, fields), context())
    assert record.title == "ab" and record.authors == "Doe, J; Roe, R" and record.keywords == "x"


def test_raw_record_is_not_modified() -> None:
    raw = RawRecord(1, {"title": " t ", "doi": "DOI:10.1/x"}, {"k": "v"}, ["n"])
    to_record(raw, context())
    assert raw.fields == {"title": " t ", "doi": "DOI:10.1/x"} and raw.extra == {"k": "v"}


# --- chain: reader -> normalise -> records.csv -> read back, against the oracle ---


def chain(reader_result, source_format: str, tmp_path: Path):  # type: ignore[no-untyped-def]
    records = to_records(reader_result, ImportContext("Src", "file", source_format))
    path = tmp_path / "records.csv"
    write_records(path, records)
    return records, read_records(path)


@pytest.mark.parametrize(
    "name",
    sorted(n.removeprefix("data/") for n, i in EXPECTED.items()
           if n.startswith("data/") and i.get("kind") == "ris"),
)
def test_ris_fixtures_through_the_whole_chain(name: str, tmp_path: Path) -> None:
    records, loaded = chain(read_ris(DATA / name), "ris", tmp_path)
    expected = EXPECTED[f"data/{name}"]
    assert loaded == records and len(records) == expected["records"]
    assert sum(r.has_abstract for r in records) == expected["abstracts"]
    assert sum(1 for r in records if r.doi) <= expected["doi_count"]
    assert len({r.study_uid for r in records}) == len(records)  # unique keys
    assert all(r.source_format == "ris" for r in records)


def test_zotero_ris_keeps_every_doi_valid_and_flags_untitled_records(tmp_path: Path) -> None:
    records, _ = chain(read_ris(DATA / "pubmed_adhd_converted-zotero.ris"), "ris", tmp_path)
    assert sum(1 for r in records if r.doi) + sum(
        1 for r in records if "doi_invalid" in r.extra_json
    ) == 546
    assert all(r.doi == r.doi.lower() and "doi.org" not in r.doi for r in records)
    assert sum(1 for r in records if not r.title) == 2


def test_nbib_and_bibtex_and_table_chains(tmp_path: Path) -> None:
    nbib, loaded = chain(read_nbib(DATA / "pubmed-adhd-set.nbib"), "nbib", tmp_path)
    assert loaded == nbib and len(nbib) == 100 and sum(r.has_abstract for r in nbib) == 94
    assert all(r.pmid for r in nbib)

    bib, loaded = chain(read_bibtex(DATA / "pubmed_adhd_converted-zotero.bib"), "bibtex", tmp_path)
    assert loaded == bib and len(bib) == 706 and sum(r.has_abstract for r in bib) == 156
    assert all(r.source_format == "bib" for r in bib)

    legacy = sorted((DATA.parent / "legacy_runs" / "project-01_dhl").glob("*.csv"))[0]
    table, loaded = chain(read_table(legacy), "csv", tmp_path)
    assert loaded == table and len(table) == 99


def test_columns_of_the_written_file_are_exactly_the_contract(tmp_path: Path) -> None:
    records, _ = chain(read_ris(DATA / "example_AB_nr4.ris"), "ris", tmp_path)
    header = (tmp_path / "records.csv").read_text(encoding="utf-8").split("\n")[0]
    assert header.split(",") == list(RECORD_COLUMNS)
    assert len(records) == 3
