"""Tests for the shared reader helpers (task T-M1-05)."""

from __future__ import annotations

from pathlib import Path

import pytest

from crapai.errors import ImportFailed
from crapai.io.readers.base import (
    RawRecord,
    ReadResult,
    decode_text,
    join_values,
    read_text_file,
    unique_in_order,
)
from crapai.io.readers.detect import SourceFormat


def test_decode_chain_and_newline_normalisation() -> None:
    assert decode_text(b"a\r\nb\rc\n") == ("a\nb\nc\n", "utf-8-sig")
    assert decode_text(b"\xef\xbb\xbfTY  - JOUR") == ("TY  - JOUR", "utf-8-sig")  # BOM removed
    assert decode_text("Größe".encode("cp1252")) == ("Größe", "cp1252")
    assert decode_text(b"\x81\x8d")[1] == "latin-1"  # bytes cp1252 does not define


def test_explicit_encoding_is_strict() -> None:
    assert decode_text("Größe".encode("cp1252"), "cp1252")[0] == "Größe"
    with pytest.raises(ImportFailed) as info:
        decode_text("Größe".encode(), "ascii")
    assert info.value.code == "E103" and "--encoding" in (info.value.hint or "")
    with pytest.raises(ImportFailed):
        decode_text(b"x", "no-such-encoding")


def test_read_text_file_reports_encoding_and_missing_file(tmp_path: Path) -> None:
    path = tmp_path / "a.ris"
    path.write_bytes("TY  - JOUR\r\nTI  - Größe\r\n".encode("cp1252"))
    assert read_text_file(path) == ("TY  - JOUR\nTI  - Größe\n", "cp1252")
    with pytest.raises(ImportFailed) as info:
        read_text_file(tmp_path / "missing.ris")
    assert info.value.code == "E101"


def test_join_and_unique_helpers() -> None:
    assert join_values(["A", "", "B"]) == "A; B"
    assert unique_in_order(["b", "a", "b", "c", "a"]) == ["b", "a", "c"]


def test_result_types_have_independent_defaults() -> None:
    first, second = RawRecord(1), RawRecord(2)
    first.fields["title"] = "x"
    first.notes.append("n")
    assert second.fields == {} and second.notes == [] and second.extra == {}
    assert ReadResult(SourceFormat.RIS, []).notes == []
