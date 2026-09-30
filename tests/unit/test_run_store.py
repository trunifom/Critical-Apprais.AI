"""Files of a run: manifest, append-only results, control file."""

from __future__ import annotations

from pathlib import Path

import pytest

from crapai.errors import StorageError
from crapai.screening.store import Manifest, ResultRow, RunState, RunStore


def store_in(tmp_path: Path) -> RunStore:
    store = RunStore(tmp_path / "runs" / "r1")
    store.create(Manifest(run_id="r1"))
    return store


def row(uid: str, status: str = "ok", **changes: object) -> ResultRow:
    return ResultRow(study_uid=uid, run_id="r1", status=status, decision="INCLUDE", **changes)  # type: ignore[arg-type]


def test_the_manifest_round_trips(tmp_path: Path) -> None:
    store = store_in(tmp_path)
    manifest = store.load_manifest()
    manifest.state = RunState.PAUSED.value
    manifest.counts = {"total": 5}
    store.save_manifest(manifest)
    again = store.load_manifest()
    assert again.state == "paused" and again.counts == {"total": 5} and again.schema_version == 1
    assert '"schema": 1' in store.manifest_path.read_text(encoding="utf-8")


def test_creating_a_run_twice_is_refused(tmp_path: Path) -> None:
    store = store_in(tmp_path)
    with pytest.raises(StorageError) as info:
        store.create(Manifest(run_id="r1"))
    assert info.value.code == "E405"


@pytest.mark.parametrize(
    "content", ["", "{", "[1]", '{"run_id": 5}', '{"unknown": 1, "run_id": "x"}']
)
def test_a_damaged_manifest_is_e404(tmp_path: Path, content: str) -> None:
    store = store_in(tmp_path)
    store.manifest_path.write_text(content, encoding="utf-8")
    with pytest.raises(StorageError) as info:
        store.load_manifest()
    assert info.value.code == "E404"


def test_results_are_appended_and_the_last_line_per_record_wins(tmp_path: Path) -> None:
    store = store_in(tmp_path)
    store.append_result(row("a", "api_error", error_code="E305"))
    store.append_result(row("b"))
    store.append_result(row("a"))  # a repeat after an error
    assert [r.study_uid for r in store.read_results()] == ["a", "b", "a"]
    latest = store.last_results()
    assert latest["a"].status == "ok" and set(latest) == {"a", "b"}


def test_no_results_file_means_no_results(tmp_path: Path) -> None:
    store = store_in(tmp_path)
    assert (
        store.read_results() == []
        and store.results_size() == 0
        and store.read_results_since(0) == []
    )


def test_a_torn_last_line_is_ignored_and_cut_before_the_next_append(tmp_path: Path) -> None:
    store = store_in(tmp_path)
    store.append_result(row("a"))
    with store.results_path.open("ab") as handle:
        handle.write(b'{"study_uid": "b", "run_')  # a crash in the middle of a line
    assert [r.study_uid for r in store.read_results()] == ["a"]
    store.append_result(row("c"))
    assert [r.study_uid for r in store.read_results()] == ["a", "c"]


def test_an_unreadable_line_in_the_middle_is_an_error_with_its_number(tmp_path: Path) -> None:
    store = store_in(tmp_path)
    store.append_result(row("a"))
    with store.results_path.open("ab") as handle:
        handle.write(b"not json\n")
    store.append_result(row("b"))
    with pytest.raises(StorageError) as info:
        store.read_results()
    assert info.value.code == "E404" and info.value.details["line"] == 2


def test_reading_since_an_offset_returns_only_the_new_lines(tmp_path: Path) -> None:
    store = store_in(tmp_path)
    store.append_result(row("a"))
    mark = store.results_size()
    store.append_result(row("b"))
    store.append_result(row("c"))
    assert [r.study_uid for r in store.read_results_since(mark)] == ["b", "c"]
    assert store.read_results_since(store.results_size()) == []


def test_a_bad_new_line_makes_the_batch_check_fail(tmp_path: Path) -> None:
    store = store_in(tmp_path)
    mark = store.results_size()
    store.results_path.write_bytes(b"garbage\n")
    with pytest.raises(StorageError):
        store.read_results_since(mark)


def test_a_full_disk_is_e403_and_other_write_errors_are_e401(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import crapai.screening.store as module

    store = store_in(tmp_path)
    for errno, code in ((28, "E403"), (13, "E401")):

        def boom(*_args: object, errno: int = errno, **_kw: object) -> None:
            raise OSError(errno, "x")

        monkeypatch.setattr(module, "append_lines", boom)
        with pytest.raises(StorageError) as info:
            store.append_result(row("a"))
        assert info.value.code == code


def test_control_requests(tmp_path: Path) -> None:
    store = store_in(tmp_path)
    assert store.read_control() is None
    store.write_control("pause")
    assert store.read_control() == "pause"
    store.write_control("stop")
    assert store.read_control() == "stop"
    store.clear_control()
    assert store.read_control() is None
    store.clear_control()  # twice is fine


@pytest.mark.parametrize("content", ["", "{", "[1]", '{"command": "explode"}'])
def test_a_broken_control_file_is_ignored(tmp_path: Path, content: str) -> None:
    store = store_in(tmp_path)
    store.control_path.write_text(content, encoding="utf-8")
    assert store.read_control() is None


def test_which_states_can_be_resumed() -> None:
    resumable = {s for s in RunState if s.resumable}
    assert resumable == {RunState.PAUSED, RunState.INTERRUPTED, RunState.FAILED, RunState.RUNNING}
