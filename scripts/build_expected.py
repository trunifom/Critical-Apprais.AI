"""Recompute record counts of the test fixtures and write tests/data/EXPECTED.json.

Counts use deliberately simple, format-level rules (no project parser), so the numbers are an
independent oracle for the future readers:
  * RIS   : number of lines matching ``ER  -``
  * NBIB  : number of lines starting with ``PMID-``
  * BibTeX: number of ``@type{`` entry starts (without @string/@comment/@preamble)
  * ZIP   : number of ``*.pdf`` members outside ``__MACOSX/`` and without ``._`` prefix

Usage: python scripts/build_expected.py
"""

from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS = [ROOT / "tests" / "data", ROOT / "tests" / "data_large"]


def count_file(path: Path) -> dict:
    info: dict = {"bytes": path.stat().st_size}
    suffix = path.suffix.lower()
    if suffix == ".zip":
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
        pdfs = [
            n
            for n in names
            if n.lower().endswith(".pdf")
            and not n.startswith("__MACOSX/")
            and not Path(n).name.startswith("._")
        ]
        info.update(kind="zip_pdf", zip_members=len(names), pdf_count=len(pdfs))
        return info
    text = path.read_bytes().decode("utf-8", errors="replace")
    if suffix == ".bib":
        pattern = r"^@(?!string|comment|preamble)[A-Za-z]+\s*\{"
        entries = re.findall(pattern, text, flags=re.M | re.I)
        info.update(kind="bibtex", records=len(entries))
    elif "PMID-" in text[:2000]:
        info.update(kind="nbib", records=len(re.findall(r"^PMID-", text, flags=re.M)))
    elif re.search(r"^TY  - ", text, flags=re.M):
        dois = [d.strip().lower() for d in re.findall(r"^DO  - (.*)$", text, flags=re.M)]
        info.update(
            kind="ris",
            records=len(re.findall(r"^ER  - ?", text, flags=re.M)),
            abstracts=len(re.findall(r"^(?:AB|N2)  - ", text, flags=re.M)),
            doi_count=len(dois),
            unique_doi=len(set(dois)),
        )
    else:
        info.update(kind="unknown")
    return info


def main() -> None:
    result: dict[str, dict] = {}
    for base in TARGETS:
        for path in sorted(base.iterdir()):
            if path.is_file() and path.name != "EXPECTED.json":
                result[f"{base.name}/{path.name}"] = count_file(path)
    # Cross-source duplicate oracle for the three synthetic example databases (DOI based).
    trio = sorted((ROOT / "tests" / "data").glob("example_db_nr*.ris"))
    all_dois: list[str] = []
    for path in trio:
        text = path.read_text(encoding="utf-8")
        all_dois += [d.strip().lower() for d in re.findall(r"^DO  - (.*)$", text, flags=re.M)]
    result["_derived/example_db_trio_merged"] = {
        "files": [p.name for p in trio],
        "records_total": len(all_dois),
        "unique_doi": len(set(all_dois)),
        "duplicates_by_doi": len(all_dois) - len(set(all_dois)),
        "note": "File name 'total-15' of example_db_nr1 is inaccurate: the file has 13 records.",
    }
    out = ROOT / "tests" / "data" / "EXPECTED.json"
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {out} ({len(result)} files)")


if __name__ == "__main__":
    main()
