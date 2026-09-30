"""Append-only files survive a crash mid-line; temp and alternative file names are unique."""

from __future__ import annotations

import datetime as dt
import threading
from pathlib import Path

import pytest

from crapai.io.import_log import ImportLogEntry, append_entry, read_entries
from crapai.prisma import events as ev
from crapai.project import atomic
from crapai.project.atomic import append_lines, atomic_write_bytes
from crapai.services.events import append_events, read_events

NOW = dt.datetime(2026, 9, 30, 14, 55, 1, tzinfo=dt.UTC)


def entry(name: str) -> ImportLogEntry:
    return ImportLogEntry(
        timestamp=NOW, source_file=name, sha256="a" * 64, source_label=name, format="ris",
        records=1, abstracts=1,
    )  # fmt: skip


def test_append_creates_the_file_and_the_folder(tmp_path: Path) -> None:
    path = tmp_path / "data" / "log.jsonl"
    append_lines(path, ["one", "two"])
    assert path.read_text(encoding="utf-8") == "one\ntwo\n"
    append_lines(path, [])  # nothing to write
    assert path.read_text(encoding="utf-8") == "one\ntwo\n"


def test_a_torn_last_line_is_cut_before_the_next_append(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    path = tmp_path / "log.jsonl"
    append_lines(path, ["complete"])
    with open(path, "ab") as handle:
        handle.write(b'{"torn":')
    with caplog.at_level("WARNING"):
        append_lines(path, ["next"])
    assert path.read_text(encoding="utf-8") == "complete\nnext\n"
    assert "Cutting 8 torn byte(s)" in caplog.text


def test_a_file_that_is_only_a_torn_line_is_emptied(tmp_path: Path) -> None:
    path = tmp_path / "log.jsonl"
    path.write_bytes(b"x" * 10000)  # longer than one read block, no newline at all
    append_lines(path, ["fresh"])
    assert path.read_text(encoding="utf-8") == "fresh\n"


def test_a_long_torn_line_after_complete_lines(tmp_path: Path) -> None:
    path = tmp_path / "log.jsonl"
    path.write_bytes(b"first\nsecond\n" + b"y" * 9000)
    append_lines(path, ["third"])
    assert path.read_text(encoding="utf-8") == "first\nsecond\nthird\n"


def test_the_import_log_stays_readable_after_a_torn_write(tmp_path: Path) -> None:
    path = tmp_path / "records.import.jsonl"
    append_entry(path, entry("a.ris"))
    with open(path, "ab") as handle:
        handle.write(b'{"schema":1,"tim')
    append_entry(path, entry("b.ris"))
    append_entry(path, entry("c.ris"))  # the third append used to break the log for good
    assert [e.source_file for e in read_entries(path)] == ["a.ris", "b.ris", "c.ris"]


def test_the_event_file_stays_readable_after_a_torn_write(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    append_events(path, [ev.source_imported("A", "a", "ris", 1)])
    with open(path, "ab") as handle:
        handle.write(b'{"step":"imp')
    append_events(path, [ev.source_imported("B", "b", "ris", 2)])
    append_events(path, [ev.source_imported("C", "c", "ris", 3)])
    assert [e.source_label for e in read_events(path)] == ["A", "B", "C"]


def test_temp_names_differ_between_calls_and_threads(tmp_path: Path) -> None:
    target = tmp_path / "f.txt"
    names = {atomic._temp_path(target) for _ in range(50)}
    assert len(names) == 50
    from_thread: list[Path] = []
    thread = threading.Thread(target=lambda: from_thread.append(atomic._temp_path(target)))
    thread.start()
    thread.join()
    assert from_thread[0] not in names


def test_two_locked_writes_in_one_second_keep_both_alternatives(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "results.xlsx"
    target.write_bytes(b"old")
    real_replace = atomic.os.replace

    def locked(src: object, dst: object) -> None:
        if Path(str(dst)) == target:
            raise PermissionError("open in Excel")
        real_replace(src, dst)  # type: ignore[arg-type]

    monkeypatch.setattr(atomic.os, "replace", locked)
    first = atomic_write_bytes(target, b"one", retries=0, now=lambda: NOW)
    second = atomic_write_bytes(target, b"two", retries=0, now=lambda: NOW)
    assert first.path != second.path and first.used_alternative and second.used_alternative
    assert first.path.read_bytes() == b"one" and second.path.read_bytes() == b"two"
    assert second.path.name == "results.20260930-145501-2.xlsx"
