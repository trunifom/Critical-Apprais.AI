"""Tests for records.csv: model, writer, reader, backups (task T-M1-10, chapters 25.7, 26.1)."""

from __future__ import annotations

import csv
import json
from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from saralocal.errors import StorageError
from saralocal.io.records_store import (
    BOOLEAN_COLUMNS,
    RECORD_COLUMNS,
    Record,
    backup_records,
    read_records,
    write_records,
)

NOW = datetime(2026, 9, 30, 15, 0, 0)


def make(**overrides: Any) -> Record:
    values: dict[str, Any] = {
        "study_uid": "e01c3819-c6df-44ef-8668-2fadcc48c543",
        "source_label": "PubMed",
        "source_file": "pubmed.ris",
        "source_row": 1,
        "source_format": "ris",
    }
    values.update(overrides)
    return Record(**values)


def test_columns_follow_chapter_26_1() -> None:
    assert len(RECORD_COLUMNS) == 40
    assert RECORD_COLUMNS[:6] == (
        "study_uid",
        "source_label",
        "source_file",
        "source_row",
        "source_format",
        "record_type",
    )
    assert RECORD_COLUMNS[-3:] == ("zip_member", "import_notes", "extra_json")
    assert len(set(RECORD_COLUMNS)) == 40
    assert set(Record.model_fields) == set(RECORD_COLUMNS)  # model and file agree
    assert {"is_retracted", "is_duplicate", "has_abstract", "has_fulltext"} == BOOLEAN_COLUMNS


def test_file_format_is_rfc4180_utf8_lf_without_bom(tmp_path: Path) -> None:
    path = tmp_path / "records.csv"
    write_records(
        path,
        [
            make(title="A, B", abstract='He said "hi"\nsecond line', year=2021, has_abstract=True),
            make(source_row=2, extra_json={"k": "ü", "n": [1, 2]}),
        ],
    )
    raw = path.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert b"\r\n" not in raw
    text = raw.decode("utf-8")
    assert text.split("\n")[0] == ",".join(RECORD_COLUMNS)
    assert '"A, B"' in text and '"He said ""hi""\nsecond line"' in text  # minimal quoting
    assert ",true," in text and ",false," in text  # lower-case booleans
    assert '{""k"":""ü"",""n"":[1,2]}' in text  # compact JSON with real Unicode, quotes doubled


def test_roundtrip_of_typical_records(tmp_path: Path) -> None:
    records = [
        make(title="T", abstract="A", has_abstract=True, year=2020, doi="10.1/x", pmid="0123"),
        make(source_row=2, is_duplicate=True, duplicate_of="uid-1", dedup_method="doi"),
        make(source_row=3, exclusion_reason="NO_ABSTRACT", exclusion_details="empty"),
        make(source_row=4, record_type="trial_registry", is_retracted=True, extra_json={"a": 1}),
    ]
    path = tmp_path / "records.csv"
    write_records(path, records)
    loaded = read_records(path)
    assert loaded == records
    assert loaded[0].pmid == "0123"  # text, leading zero kept
    assert loaded[1].year is None  # empty stays null


TEXT = st.text(alphabet=st.characters(exclude_categories=["Cs"]))
NONEMPTY = st.text(alphabet=st.characters(exclude_categories=["Cs"]), min_size=1)
JSON_VALUES = st.recursive(
    st.none() | st.booleans() | st.integers(-(2**53), 2**53) | TEXT,
    lambda children: st.lists(children, max_size=3) | st.dictionaries(TEXT, children, max_size=3),
    max_leaves=8,
)


@settings(
    max_examples=150,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(
    title=TEXT,
    abstract=TEXT,
    authors=TEXT,
    label=NONEMPTY,
    year=st.none() | st.integers(1400, 2100),
    flags=st.tuples(st.booleans(), st.booleans(), st.booleans(), st.booleans()),
    extra=st.dictionaries(TEXT, JSON_VALUES, max_size=4),
)
def test_write_then_read_is_lossless_for_arbitrary_text(
    tmp_path: Path,
    title: str,
    abstract: str,
    authors: str,
    label: str,
    year: int | None,
    flags: tuple[bool, bool, bool, bool],
    extra: dict[str, Any],
) -> None:
    """Property: commas, quotes, line breaks (LF, CR, CRLF), controls and any Unicode survive."""
    record = make(
        title=title,
        abstract=abstract,
        authors=authors,
        source_label=label,
        year=year,
        is_retracted=flags[0],
        is_duplicate=flags[1],
        has_abstract=flags[2],
        has_fulltext=flags[3],
        extra_json=extra,
    )
    second = record.model_copy(update={"source_row": 2})
    path = tmp_path / "records.csv"
    write_records(path, [record, second])
    assert read_records(path) == [record, second]


def test_awkward_strings_explicitly(tmp_path: Path) -> None:
    nasty = 'a,b"c\r\nd\ne\rf\tg\x00h ,\n"   \U0001f9ec  '
    record = make(title=nasty, abstract=nasty, extra_json={"k": nasty})
    path = tmp_path / "records.csv"
    write_records(path, [record])
    assert read_records(path) == [record]


def test_missing_and_empty_files_mean_no_records(tmp_path: Path) -> None:
    assert read_records(tmp_path / "none.csv") == []
    empty = tmp_path / "empty.csv"
    empty.write_bytes(b"")
    assert read_records(empty) == []
    write_records(tmp_path / "zero.csv", [])
    assert read_records(tmp_path / "zero.csv") == []  # header only


def test_bom_added_by_excel_is_tolerated(tmp_path: Path) -> None:
    path = tmp_path / "records.csv"
    write_records(path, [make(title="T")])
    path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes())
    assert read_records(path)[0].title == "T"


def test_wrong_header_is_reported_with_missing_and_unknown_columns(tmp_path: Path) -> None:
    path = tmp_path / "records.csv"
    write_records(path, [make()])
    text = path.read_text(encoding="utf-8").replace("study_uid", "uid", 1)
    path.write_text(text, encoding="utf-8", newline="")
    with pytest.raises(StorageError) as info:
        read_records(path)
    assert info.value.code == "E404"
    assert info.value.details["missing"] == ["study_uid"]
    assert info.value.details["unknown"] == ["uid"]


def test_invalid_rows_are_reported_with_the_line_number(tmp_path: Path) -> None:
    path = tmp_path / "records.csv"
    write_records(path, [make(), make(source_row=2)])
    lines = path.read_text(encoding="utf-8").split("\n")
    lines[2] = lines[2].replace(",ris,", ",docx,", 1)  # second record: unknown source_format
    path.write_text("\n".join(lines), encoding="utf-8", newline="")
    with pytest.raises(StorageError) as info:
        read_records(path)
    assert "line 3" in info.value.user_message and "source_format" in info.value.user_message
    short = tmp_path / "short.csv"
    short.write_text(",".join(RECORD_COLUMNS) + "\nonly,two\n", encoding="utf-8", newline="")
    with pytest.raises(StorageError) as info2:
        read_records(short)
    assert "cells" in info2.value.user_message


def test_bad_boolean_cell_is_an_error(tmp_path: Path) -> None:
    path = tmp_path / "records.csv"
    write_records(path, [make()])
    text = path.read_text(encoding="utf-8").replace("false", "maybe", 1)
    path.write_text(text, encoding="utf-8", newline="")
    with pytest.raises(StorageError):
        read_records(path)


@pytest.mark.parametrize(
    "overrides",
    [
        {"source_format": "docx"},
        {"record_type": "novel"},
        {"exclusion_reason": "BORING"},
        {"study_uid": ""},
        {"source_row": 0},
        {"unknown_column": "x"},
    ],
)
def test_model_rejects_values_outside_the_contract(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        make(**overrides)


def test_write_is_atomic_and_leaves_no_temp_files(tmp_path: Path) -> None:
    path = tmp_path / "records.csv"
    write_records(path, [make()])
    write_records(path, [make(), make(source_row=2)])
    assert sorted(p.name for p in tmp_path.iterdir()) == ["records.csv"]
    assert len(read_records(path)) == 2


def test_failed_write_keeps_the_old_file(tmp_path: Path) -> None:
    path = tmp_path / "records.csv"
    write_records(path, [make(title="old")])

    def exploding() -> Iterator[Record]:
        yield make(title="new")
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        write_records(path, exploding())
    assert read_records(path)[0].title == "old"


def test_backups_are_written_before_replacing_and_only_five_are_kept(tmp_path: Path) -> None:
    path = tmp_path / "data" / "records.csv"
    path.parent.mkdir()
    backup_dir = path.parent / ".backup"
    write_records(path, [make(title="v0")], backup_dir=backup_dir, now=NOW)
    assert not backup_dir.exists()  # nothing to back up on the first write
    for version in range(1, 8):
        write_records(
            path,
            [make(title=f"v{version}")],
            backup_dir=backup_dir,
            now=NOW + timedelta(seconds=version),
        )
    backups = sorted(backup_dir.glob("records.*.csv"))
    assert len(backups) == 5
    newest = backups[-1].read_bytes().decode("utf-8")
    assert "v6" in newest and "v7" not in newest  # the copy holds the state BEFORE the write
    assert read_records(path)[0].title == "v7"


def test_backup_records_returns_none_without_a_file(tmp_path: Path) -> None:
    assert backup_records(tmp_path / "nope.csv", tmp_path / "b", now=NOW) is None


def test_csv_can_be_parsed_by_a_plain_csv_reader(tmp_path: Path) -> None:
    """RFC 4180 check with the standard library: what Excel or pandas would see."""
    path = tmp_path / "records.csv"
    write_records(path, [make(title="x,y", abstract="line1\nline2", extra_json={"a": "b"})])
    with open(path, encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["title"] == "x,y" and rows[0]["abstract"] == "line1\nline2"
    assert json.loads(rows[0]["extra_json"]) == {"a": "b"}


def test_locked_file_is_an_error_unless_an_alternative_is_allowed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    from saralocal.project import atomic

    path = tmp_path / "records.csv"
    write_records(path, [make(title="old")])
    real_replace = os.replace

    def locked(src: object, dst: object) -> None:
        if Path(str(dst)) == path:
            raise PermissionError("open in Excel")
        real_replace(src, dst)  # type: ignore[arg-type]

    monkeypatch.setattr(atomic.os, "replace", locked)
    monkeypatch.setattr(atomic.time, "sleep", lambda seconds: None)
    with pytest.raises(StorageError) as info:
        write_records(path, [make(title="new")])
    assert info.value.code == "E401"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["records.csv"]  # no side file
    assert read_records(path)[0].title == "old"

    written = write_records(path, [make(title="new")], allow_alternative=True)
    assert written != path and read_records(written)[0].title == "new"
    assert read_records(path)[0].title == "old"
