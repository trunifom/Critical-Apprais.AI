"""The licence of the code (ADR 0016): PolyForm Noncommercial 1.0.0, text unchanged."""

from __future__ import annotations

import hashlib
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LICENSE = (ROOT / "LICENSE").read_bytes().replace(b"\r\n", b"\n")

# SHA-256 of the licence text as published by the PolyForm project (tag 1.0.0), without our notice.
UPSTREAM_SHA256 = "c0ea4a896d2c8c394b29f9427589996db826cd501c512279ff0ed3ef48fabbe5"
SPDX = "PolyForm-Noncommercial-1.0.0"


def test_licence_text_is_the_unmodified_polyform_text_after_the_notice() -> None:
    notice, _, body = LICENSE.partition(b"\n\n")
    assert notice.startswith(b"Required Notice: Copyright")
    assert hashlib.sha256(body).hexdigest() == UPSTREAM_SHA256


def test_required_notice_is_a_single_plain_text_line() -> None:
    first = LICENSE.split(b"\n", 1)[0]
    assert first.startswith(b"Required Notice: ") and b"Critical Apprais.AI" in first


def test_pyproject_declares_the_same_licence() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["license"] == SPDX
    assert "LICENSE" in project["license-files"]


def test_documents_state_the_licence_and_its_limits() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    adr = (ROOT / "docs" / "adr" / "0016-lizenz-polyform-noncommercial.md").read_text(
        encoding="utf-8"
    )
    assert "PolyForm Noncommercial" in readme and "nicht kommerziell" in readme
    assert "source available" in adr and "OSI" in adr  # honest about "not open source"
    assert "Fremdmaterial" in adr
