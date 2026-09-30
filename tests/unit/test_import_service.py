"""Tests for the import service (task T-M1-11, plan chapter 8.2)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from saralocal.errors import ImportFailed, StorageError
from saralocal.io.import_log import read_entries, sha256_file
from saralocal.io.records_store import read_records
from saralocal.project.workspace import Workspace
from saralocal.services.importing import ImportRequest, import_source

DATA = Path(__file__).resolve().parents[2] / "tests" / "data"
EXPECTED = json.loads((DATA / "EXPECTED.json").read_text(encoding="utf-8"))


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    return Workspace.create(tmp_path / "review")


def run(workspace: Workspace, name: str, label: str | None = "A", **options: object):  # type: ignore[no-untyped-def]
    return import_source(workspace, ImportRequest(DATA / name, label=label, **options))  # type: ignore[arg-type]


def test_import_ris_writes_records_source_copy_and_log(workspace: Workspace) -> None:
    summary = run(workspace, "example_db_nr2_total-10_duplicates-3.ris")
    assert (summary.records, summary.total_records, summary.format) == (10, 10, "ris")
    records = read_records(workspace.records_csv)
    assert len(records) == 10
    assert {r.source_label for r in records} == {"A"}
    assert {r.source_file for r in records} == {"example_db_nr2_total-10_duplicates-3.ris"}
    assert [r.source_row for r in records] == list(range(1, 11))
    assert len({r.study_uid for r in records}) == 10
    stored = workspace.sources_dir / "example_db_nr2_total-10_duplicates-3.ris"
    assert stored.read_bytes() == (DATA / stored.name).read_bytes()  # original kept unchanged
    (entry,) = read_entries(workspace.import_log)
    assert entry.sha256 == sha256_file(stored) and entry.records == 10 and entry.source_label == "A"
    assert not workspace.lock_file.exists()  # lock released


def test_import_counts_equal_the_oracle_for_all_bibliographic_fixtures(tmp_path: Path) -> None:
    for name, info in EXPECTED.items():
        if not name.startswith("data/") or info.get("kind") not in {"ris", "nbib", "bibtex"}:
            continue
        workspace = Workspace.create(tmp_path / name.replace("/", "_"))
        summary = import_source(workspace, ImportRequest(DATA / name.removeprefix("data/")))
        assert summary.records == info["records"], name
        assert len(read_records(workspace.records_csv)) == info["records"]
        if "abstracts" in info:
            assert summary.abstracts == info["abstracts"], name


def test_second_import_appends_and_keeps_the_first_records(workspace: Workspace) -> None:
    first = run(workspace, "example_db_nr1_total-15_duplicates-0.ris", label="Db1")
    before = read_records(workspace.records_csv)
    second = run(workspace, "example_db_nr3_total-8_duplicates-2.ris", label="Db3")
    after = read_records(workspace.records_csv)
    assert (first.records, second.records, second.total_records) == (13, 8, 21)
    assert after[:13] == before  # existing rows are untouched, same study_uids
    assert [r.source_label for r in after[13:]] == ["Db3"] * 8
    assert [e.source_label for e in read_entries(workspace.import_log)] == ["Db1", "Db3"]
    assert list(workspace.backup_dir.glob("records.*.csv"))  # backup made before the rewrite


def test_repeated_file_is_refused_with_e106_and_changes_nothing(workspace: Workspace) -> None:
    run(workspace, "example_AB_nr4.ris")
    before = workspace.records_csv.read_bytes()
    with pytest.raises(ImportFailed) as info:
        run(workspace, "example_AB_nr4.ris")
    assert info.value.code == "E106"
    # Same bytes under another name and extension are caught too.
    with pytest.raises(ImportFailed) as info2:
        run(workspace, "example_AB_nr4.txt")
    assert info2.value.code == "E106"
    assert workspace.records_csv.read_bytes() == before
    assert len(read_entries(workspace.import_log)) == 1


def test_force_imports_again_and_reuses_the_identical_source_file(workspace: Workspace) -> None:
    run(workspace, "example_AB_nr4.ris")
    summary = run(workspace, "example_AB_nr4.ris", force=True)
    assert summary.total_records == 6
    assert sorted(p.name for p in workspace.sources_dir.iterdir()) == ["example_AB_nr4.ris"]
    entries = read_entries(workspace.import_log)
    assert [e.forced for e in entries] == [False, True]
    assert len({r.study_uid for r in read_records(workspace.records_csv)}) == 6  # new uids


def test_same_name_but_different_content_gets_a_new_source_name(
    workspace: Workspace, tmp_path: Path
) -> None:
    other = tmp_path / "incoming" / "export.ris"
    other.parent.mkdir()
    other.write_text("TY  - JOUR\nTI  - One\nAB  - a\nER  - \n", encoding="utf-8")
    import_source(workspace, ImportRequest(other))
    other.write_text("TY  - JOUR\nTI  - Two\nAB  - b\nER  - \n", encoding="utf-8")
    summary = import_source(workspace, ImportRequest(other))
    assert summary.source_file == "export-2.ris"
    assert sorted(p.name for p in workspace.sources_dir.iterdir()) == ["export-2.ris", "export.ris"]
    assert "One" in (workspace.sources_dir / "export.ris").read_text(encoding="utf-8")


def test_default_label_is_the_file_stem(workspace: Workspace) -> None:
    summary = run(workspace, "example_AB_nr4.ris", label=None)
    assert summary.source_label == "example_AB_nr4"


def test_mismatched_extension_is_explained_in_summary_and_log(workspace: Workspace) -> None:
    summary = run(workspace, "pubmed-adhd-set.ris")
    assert summary.format == "nbib" and summary.records == 100
    assert "although the extension says .ris" in summary.format_reason
    (entry,) = read_entries(workspace.import_log)
    assert entry.notes[0].startswith("content has MEDLINE")
    assert {r.source_format for r in read_records(workspace.records_csv)} == {"nbib"}


def test_table_import_stores_the_mapping_in_the_log(workspace: Workspace, tmp_path: Path) -> None:
    table = tmp_path / "in.csv"
    table.write_text("Name,Body\nPaper one,Text one\nPaper two,Text two\n", encoding="utf-8")
    with pytest.raises(ImportFailed) as info:
        import_source(workspace, ImportRequest(table))
    assert info.value.code == "E104"
    assert not list(workspace.sources_dir.iterdir()) and not workspace.import_log.exists()
    summary = import_source(
        workspace, ImportRequest(table, mapping={"title": "Name", "abstract": "Body"})
    )
    assert summary.column_map == {"title": "Name", "abstract": "Body"}
    (entry,) = read_entries(workspace.import_log)
    assert entry.column_map == {"title": "Name", "abstract": "Body"}
    assert entry.options["delimiter"] == ","


def test_failed_reads_leave_no_trace(workspace: Workspace, tmp_path: Path) -> None:
    bad = tmp_path / "bad.txt"
    bad.write_text("Dear all, please find attached\n", encoding="utf-8")
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.7\n...")
    for path in (bad, pdf, tmp_path / "missing.ris"):
        with pytest.raises(ImportFailed) as info:
            import_source(workspace, ImportRequest(path))
        assert info.value.code == "E101"
    assert not any(workspace.sources_dir.iterdir())
    assert not workspace.records_csv.exists() and not workspace.import_log.exists()
    assert not workspace.lock_file.exists()


def test_lock_held_by_another_process_blocks_the_import(workspace: Workspace) -> None:
    holder = workspace.lock()
    holder.acquire()
    try:
        with pytest.raises(StorageError) as info:
            run(workspace, "example_AB_nr4.ris")
        assert info.value.code == "E402"
    finally:
        holder.release()
    assert not workspace.records_csv.exists()
    run(workspace, "example_AB_nr4.ris")  # works once the lock is free


def test_non_project_folder_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(StorageError) as info:
        import_source(Workspace(tmp_path), ImportRequest(DATA / "example_AB_nr4.ris"))
    assert info.value.code == "E404"


def test_damaged_records_csv_is_not_overwritten(workspace: Workspace) -> None:
    run(workspace, "example_AB_nr4.ris")
    workspace.records_csv.write_text("not,the,right,header\n1,2,3,4\n", encoding="utf-8")
    damaged = workspace.records_csv.read_bytes()
    with pytest.raises(StorageError) as info:
        run(workspace, "example_db_nr1_total-15_duplicates-0.ris")
    assert info.value.code == "E404"
    assert workspace.records_csv.read_bytes() == damaged
    assert len(read_entries(workspace.import_log)) == 1  # the failed import is not logged


def test_warnings_for_missing_abstracts_and_empty_records(
    workspace: Workspace, tmp_path: Path
) -> None:
    no_abstracts = run(workspace, "example_db_nr1_total-15_duplicates-0.ris")
    assert no_abstracts.warnings == ("no_abstracts",)
    mixed = tmp_path / "mixed.ris"
    mixed.write_text(
        "TY  - JOUR\nTI  - A\nAB  - has abstract\nER  - \n"
        "TY  - JOUR\nAU  - Only, Author\nER  - \n",
        encoding="utf-8",
    )
    summary = import_source(workspace, ImportRequest(mixed))
    assert summary.empty_records == 1 and "empty_records" in summary.warnings
    records = read_records(workspace.records_csv)
    assert [r.exclusion_reason for r in records[-2:]] == ["", "EMPTY_RECORD"]
    assert len(records) == 13 + 2  # the empty record is kept, only marked


def test_source_file_is_never_modified(workspace: Workspace, tmp_path: Path) -> None:
    original = tmp_path / "keep.ris"
    shutil.copyfile(DATA / "citation-export.ris", original)
    digest = sha256_file(original)
    import_source(workspace, ImportRequest(original))
    assert sha256_file(original) == digest
    assert sha256_file(workspace.sources_dir / "keep.ris") == digest
