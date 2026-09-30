"""Regression tests for defects found in the review of the import code."""

from __future__ import annotations

import codecs
import logging
from pathlib import Path
from typing import Any

import pytest
import yaml

from crapai.errors import ImportFailed, StorageError
from crapai.io.import_log import read_entries, sha256_file
from crapai.io.normalize import normalize_doi
from crapai.io.readers.base import decode_text
from crapai.io.readers.bibtex import parse_bibtex_text
from crapai.io.readers.detect import SourceFormat, detect_format
from crapai.io.readers.dispatch import read_source
from crapai.io.readers.nbib import parse_nbib_text
from crapai.io.readers.ris import parse_ris_text
from crapai.io.readers.tabular import read_table
from crapai.io.records_store import backup_records, read_records
from crapai.project.workspace import Workspace
from crapai.services import importing
from crapai.services.importing import ImportRequest, import_source
from crapai.services.project import create_project

RIS = "TY  - JOUR\nTI  - A title\nAB  - An abstract\nER  - \n"
NOW = __import__("datetime").datetime(2026, 9, 30, 12, 0, 0)


@pytest.fixture
def project(tmp_path: Path) -> Workspace:
    return create_project(tmp_path / "p", template="demo")


# --- encodings ---------------------------------------------------------------------------------


def test_an_explicit_utf8_keeps_no_byte_order_mark_in_the_text() -> None:
    text, used = decode_text(codecs.BOM_UTF8 + RIS.encode("utf-8"), "utf-8")
    assert text.startswith("TY") and used == "utf-8"


def test_a_ris_file_with_bom_and_explicit_utf8_is_read(tmp_path: Path) -> None:
    path = tmp_path / "bom.ris"
    path.write_bytes(codecs.BOM_UTF8 + RIS.encode("utf-8"))
    result, _ = read_source(path, encoding="utf-8")
    assert [r.fields["title"] for r in result.records] == ["A title"]  # used to be E102


def test_utf16_files_are_detected_and_read(tmp_path: Path) -> None:
    path = tmp_path / "excel.txt"
    path.write_bytes(
        codecs.BOM_UTF16_LE + "title\tabstract\nA\tSome abstract\nB\tAnother\n".encode("utf-16-le")
    )
    assert detect_format(path).format is SourceFormat.TSV
    result, _ = read_source(path)
    assert [r.fields["title"] for r in result.records] == ["A", "B"] and result.encoding == "utf-16"


def test_utf16_ris_is_read_with_the_bom_of_the_file(tmp_path: Path) -> None:
    path = tmp_path / "u.ris"
    path.write_bytes(RIS.encode("utf-16"))  # writes a BOM
    result, _ = read_source(path)
    assert result.records[0].fields["title"] == "A title"


def test_a_legacy_code_page_gets_a_visible_note(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    path = tmp_path / "cp.ris"
    path.write_bytes("TY  - JOUR\nTI  - Größe\nAB  - Über\nER  - \n".encode("cp1252"))
    with caplog.at_level(logging.WARNING):
        result, _ = read_source(path)
    assert result.encoding == "cp1252" and result.records[0].fields["title"] == "Größe"
    assert "not valid UTF-8" in result.notes[0] and "cp1252" in result.notes[0]
    assert "not valid UTF-8" in caplog.text


def test_utf8_files_get_no_encoding_note(tmp_path: Path) -> None:
    path = tmp_path / "ok.ris"
    path.write_text(RIS, encoding="utf-8")
    assert read_source(path)[0].notes == []


# --- format detection --------------------------------------------------------------------------


def test_ris_with_a_single_space_before_the_dash_is_recognised() -> None:
    from crapai.io.readers.detect import _sniff_bibliographic

    found = _sniff_bibliographic("TY - JOUR\nTI - A title\nER - \n")
    assert found is not None and found[0] is SourceFormat.RIS


@pytest.mark.parametrize(
    "name,expected", [("one.csv", SourceFormat.CSV), ("one.tsv", SourceFormat.TSV)]
)
def test_a_single_column_table_is_taken_from_the_extension(
    tmp_path: Path, name: str, expected: SourceFormat
) -> None:
    path = tmp_path / name
    path.write_text("title\nA\nB\nC\n", encoding="utf-8")
    assert detect_format(path).format is expected  # used to be E101 "not recognised"
    result = read_table(path)
    assert [r.fields["title"] for r in result.records] == ["A", "B", "C"]


@pytest.mark.parametrize(
    "value,char", [("\\t", "\t"), ("tab", "\t"), ("semicolon", ";"), (";", ";")]
)
def test_delimiter_names_are_understood(tmp_path: Path, value: str, char: str) -> None:
    path = tmp_path / "d.csv"
    path.write_text(f"title{char}abstract\nA{char}text\nB{char}more\n", encoding="utf-8")
    result = read_table(path, delimiter=value)
    assert [r.fields["abstract"] for r in result.records] == ["text", "more"]


@pytest.mark.parametrize("value", ["::", "ab", "\\x"])
def test_a_delimiter_of_more_than_one_character_is_e104_not_a_type_error(
    tmp_path: Path, value: str
) -> None:
    path = tmp_path / "d.csv"
    path.write_text("title,abstract\nA,x\nB,y\n", encoding="utf-8")
    with pytest.raises(ImportFailed) as info:
        read_table(path, delimiter=value)
    assert info.value.code == "E104"


def test_a_damaged_worksheet_is_e101(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    openpyxl = pytest.importorskip("openpyxl")
    path = tmp_path / "s.xlsx"
    book = openpyxl.Workbook()
    book.active.append(["title", "abstract"])
    book.active.append(["A", "x"])
    book.save(path)

    def broken(self: Any, *args: Any, **kwargs: Any) -> Any:
        raise KeyError("sheet xml is corrupt")

    monkeypatch.setattr("openpyxl.worksheet._read_only.ReadOnlyWorksheet.iter_rows", broken)
    with pytest.raises(ImportFailed) as info:
        read_table(path)
    assert info.value.code == "E101" and "damaged" in info.value.user_message


# --- no data is lost ---------------------------------------------------------------------------


def test_ris_keeps_the_full_date_and_second_pages() -> None:
    text = (
        "TY  - JOUR\nTI  - T\nPY  - 2020\nDA  - 2020/03/15/\nSP  - 10\nEP  - 20\nSP  - e5\nER  - \n"
    )
    record = parse_ris_text(text).records[0]
    assert record.fields["year"] == 2020 and record.fields["pages"] == "10-20"
    assert record.extra["ris_DA"] == "2020/03/15/" and record.extra["ris_SP"] == "e5"


def test_ris_date_that_only_repeats_the_year_is_not_kept_twice() -> None:
    record = parse_ris_text("TY  - JOUR\nTI  - T\nPY  - 2020\nDA  - 2020///\nER  - \n").records[0]
    assert "ris_DA" not in record.extra


def test_ris_with_only_a_start_page_still_works() -> None:
    record = parse_ris_text("TY  - JOUR\nTI  - T\nSP  - 7\nER  - \n").records[0]
    assert record.fields["pages"] == "7"


def test_bibtex_alternatives_and_repeats_stay_in_extra() -> None:
    text = (
        "@article{k,\n title={X}, title={Y}, journal={J}, booktitle={B}, issn={1}, isbn={2},\n"
        " year={2020}, date={2020-05-01}\n}\n"
    )
    record = parse_bibtex_text(text).records[0]
    assert record.fields["title"] == "X" and record.fields["journal"] == "J"
    assert record.extra["bib_title"] == "Y"
    assert record.extra["bib_booktitle"] == "B" and record.extra["bib_isbn"] == "2"
    assert record.extra["bib_date"] == "2020-05-01"


def test_nbib_blocks_without_pmid_are_kept_when_the_file_has_pmid_records() -> None:
    text = "PMID- 1\nTI  - First\n\nTI  - Second without PMID\nAB  - text\n\nXX  - stray\n"
    result = parse_nbib_text(text)
    assert [r.fields["title"] for r in result.records] == ["First", "Second without PMID"]
    assert any("1 block(s) without PMID, title or abstract were skipped" in n for n in result.notes)


def test_a_ris_file_is_never_read_as_nbib_even_with_titles() -> None:
    with pytest.raises(ImportFailed) as info:
        parse_nbib_text("TY  - JOUR\nTI  - T\nER  - \n")
    assert info.value.code == "E102"


@pytest.mark.parametrize(
    "raw,doi",
    [
        ("https://www.doi.org/10.1000/abc", "10.1000/abc"),
        ("http://dx.doi.org/10.1000/abc", "10.1000/abc"),
        ("https://doi.org/10.1000/ABC", "10.1000/abc"),
        ("doi:10.1000/abc", "10.1000/abc"),
        ("DOI 10.1000/abc", "10.1000/abc"),
        ("10.1000/abc.", "10.1000/abc"),
    ],
)
def test_doi_prefixes(raw: str, doi: str) -> None:
    assert normalize_doi(raw) == doi


# --- files and logs fail cleanly ----------------------------------------------------------------


def test_hashing_an_unreadable_file_is_e101(tmp_path: Path) -> None:
    with pytest.raises(ImportFailed) as info:
        sha256_file(tmp_path / "missing.ris")
    assert info.value.code == "E101"


def test_a_non_utf8_import_log_is_e404(tmp_path: Path) -> None:
    log = tmp_path / "records.import.jsonl"
    log.write_bytes(b"\xff\xfe\x00")
    with pytest.raises(StorageError) as info:
        read_entries(log)
    assert info.value.code == "E404"


def test_a_non_utf8_records_file_is_e404_with_a_backup_hint(project: Workspace) -> None:
    project.records_csv.parent.mkdir(parents=True, exist_ok=True)
    project.records_csv.write_bytes("study_uid,title\nx,Größe\n".encode("cp1252"))
    with pytest.raises(StorageError) as info:
        read_records(project.records_csv)
    assert info.value.code == "E404" and "backup" in (info.value.hint or "")


def test_a_csv_error_in_records_is_e404(
    project: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    import crapai.io.records_store as store

    project.records_csv.write_text("study_uid\n", encoding="utf-8")
    monkeypatch.setattr(
        store, "_read_records", lambda path: (_ for _ in ()).throw(store.csv.Error("x"))
    )
    with pytest.raises(StorageError) as info:
        read_records(project.records_csv)
    assert info.value.code == "E404"


def test_copy_errors_become_storage_errors_and_leave_no_partial_file(
    project: Workspace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "a.ris"
    source.write_text(RIS, encoding="utf-8")

    def full_disk(src: Any, dst: Any) -> None:
        Path(dst).write_bytes(b"partial")
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(importing.shutil, "copyfile", full_disk)
    with pytest.raises(StorageError) as info:
        import_source(project, ImportRequest(source))
    assert info.value.code == "E403" and "nothing was imported" in (info.value.hint or "")
    assert list(project.sources_dir.iterdir()) == [] and not project.records_csv.exists()


def test_a_failing_import_log_says_not_to_import_again(
    project: Workspace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "a.ris"
    source.write_text(RIS, encoding="utf-8")

    def refuse(path: Path, entry: object) -> None:
        raise OSError("log is locked")

    monkeypatch.setattr(importing, "append_entry", refuse)
    with pytest.raises(StorageError) as info:
        import_source(project, ImportRequest(source))
    assert info.value.code == "E401" and "Do not import this file again" in (info.value.hint or "")
    assert len(read_records(project.records_csv)) == 1  # the records are there


def test_retrying_a_locked_write_does_not_flood_the_backups(tmp_path: Path) -> None:
    records = tmp_path / "records.csv"
    records.write_text("a,b\n1,2\n", encoding="utf-8")
    backups = tmp_path / ".backup"
    import datetime as dt

    times = [dt.datetime(2026, 9, 30, 12, 0, s) for s in range(6)]
    for moment in times:  # six attempts with identical content
        backup_records(records, backups, now=moment)
    assert len(list(backups.glob("records.*.csv"))) == 1
    records.write_text("a,b\n1,3\n", encoding="utf-8")
    backup_records(records, backups, now=times[-1] + dt.timedelta(seconds=1))
    assert len(list(backups.glob("records.*.csv"))) == 2


# --- project title -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "title", ["C:\\Users\\x", "Line one\nline two", 'Ünïcode "quoted" title', "tab\there"]
)
def test_any_title_gives_a_valid_project_yaml(tmp_path: Path, title: str) -> None:
    workspace = create_project(tmp_path / "p", title=title)
    data = yaml.safe_load(workspace.project_yaml.read_text(encoding="utf-8"))
    assert data["project"]["title"] == title
