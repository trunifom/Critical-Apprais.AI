"""Tests for the import log and source hashes (task T-M1-10, error E106)."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from crapai.errors import ImportFailed, StorageError
from crapai.io.import_log import (
    ImportLogEntry,
    append_entry,
    ensure_not_imported,
    find_previous_import,
    read_entries,
    sha256_file,
)

ZURICH = timezone(timedelta(hours=2))
DATA = Path(__file__).resolve().parents[2] / "tests" / "data"


def entry(sha: str = "a" * 64, **overrides: object) -> ImportLogEntry:
    values: dict[str, object] = {
        "timestamp": datetime(2026, 9, 30, 15, 30, tzinfo=ZURICH),
        "source_file": "pubmed.ris",
        "sha256": sha,
        "source_label": "PubMed",
        "format": "ris",
        "records": 10,
        "abstracts": 7,
    }
    values.update(overrides)
    return ImportLogEntry(**values)  # type: ignore[arg-type]


def test_sha256_matches_hashlib_and_handles_large_and_empty_files(tmp_path: Path) -> None:
    sample = DATA / "example_AB_nr4.ris"
    assert sha256_file(sample) == hashlib.sha256(sample.read_bytes()).hexdigest()
    big = tmp_path / "big.bin"
    big.write_bytes(b"x" * (3 * 1024 * 1024 + 17))  # several read chunks
    assert sha256_file(big) == hashlib.sha256(big.read_bytes()).hexdigest()
    empty = tmp_path / "empty"
    empty.write_bytes(b"")
    assert sha256_file(empty) == hashlib.sha256(b"").hexdigest()


def test_the_two_identical_pubmed_fixtures_share_a_hash() -> None:
    """pubmed-adhd-set.ris and .nbib are byte-identical; a second import must be caught."""
    assert sha256_file(DATA / "pubmed-adhd-set.ris") == sha256_file(DATA / "pubmed-adhd-set.nbib")
    assert sha256_file(DATA / "example_AB_nr4.ris") == sha256_file(DATA / "example_AB_nr4.txt")
    assert sha256_file(DATA / "example_db_nr1_total-15_duplicates-0.ris") != sha256_file(
        DATA / "example_db_nr2_total-10_duplicates-3.ris"
    )


def test_append_and_read_roundtrip_as_compact_json_lines(tmp_path: Path) -> None:
    log = tmp_path / "data" / "records.import.jsonl"  # parent folder is created
    first = entry(encoding="cp1252", options={"delimiter": ";"}, column_map={"title": "Titel"})
    second = entry("b" * 64, source_label="Größe", notes=["a", "b"], forced=True)
    append_entry(log, first)
    append_entry(log, second)
    raw = log.read_text(encoding="utf-8")
    assert raw.count("\n") == 2 and "\r" not in raw
    parsed = [json.loads(line) for line in raw.splitlines()]
    assert parsed[0]["schema"] == 1 and parsed[0]["timestamp"].startswith("2026-09-30T15:30")
    assert "Größe" in raw  # ensure_ascii is off
    assert read_entries(log) == [first, second]


def test_missing_log_is_empty(tmp_path: Path) -> None:
    assert read_entries(tmp_path / "none.jsonl") == []
    assert find_previous_import(tmp_path / "none.jsonl", "a" * 64) is None


def test_reimport_is_detected_by_hash_and_names_the_earlier_import(tmp_path: Path) -> None:
    log = tmp_path / "log.jsonl"
    append_entry(log, entry("a" * 64, source_file="first.ris"))
    append_entry(log, entry("b" * 64, source_file="other.ris"))
    ensure_not_imported(log, "c" * 64)  # a new file passes
    with pytest.raises(ImportFailed) as info:
        ensure_not_imported(log, "a" * 64)
    error = info.value
    assert error.code == "E106"
    assert "first.ris" in error.user_message and "--force" in (error.hint or "")
    assert error.details["source_label"] == "PubMed"
    ensure_not_imported(log, "a" * 64, force=True)  # --force allows it


def test_latest_entry_wins_when_a_file_was_forced_twice(tmp_path: Path) -> None:
    log = tmp_path / "log.jsonl"
    append_entry(log, entry(source_file="one.ris"))
    append_entry(log, entry(source_file="two.ris", forced=True))
    previous = find_previous_import(log, "a" * 64)
    assert previous is not None and previous.source_file == "two.ris"


def test_half_written_last_line_is_ignored(tmp_path: Path) -> None:
    log = tmp_path / "log.jsonl"
    append_entry(log, entry())
    with open(log, "a", encoding="utf-8") as handle:
        handle.write('{"schema":1,"timestamp":"2026-09-30T15')  # crash while writing
    assert read_entries(log) == [entry()]


def test_unreadable_line_in_the_middle_is_an_error(tmp_path: Path) -> None:
    log = tmp_path / "log.jsonl"
    append_entry(log, entry())
    with open(log, "a", encoding="utf-8") as handle:
        handle.write("not json\n")
    append_entry(log, entry("b" * 64))
    with pytest.raises(StorageError) as info:
        read_entries(log)
    assert info.value.code == "E404" and "line 2" in info.value.user_message


def test_entry_validation() -> None:
    with pytest.raises(ValueError):
        entry(sha="short")
    with pytest.raises(ValueError):
        entry(records=-1)
    with pytest.raises(ValueError):
        ImportLogEntry(**{**entry().model_dump(), "surprise": 1})  # type: ignore[arg-type]
