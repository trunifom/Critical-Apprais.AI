# tests/data_large/

Large fixtures that are **not versioned** (see `.gitignore`). They were copied from SARA-App on 2026-09-30.

| Path | Size | Use |
|---|---|---|
| `citation-export_2.bib` | 11.5 MB, 1343 entries | Performance test of the BibTeX reader (task T-M1-07), CRLF, very long lines |
| `test.zip` | 25.5 MB | 6 PDFs (+ 6 `__MACOSX` entries) for the PDF-ZIP reader (T-M1-09). The PDFs are third-party papers |
| `prisma_snapshots/Review Task <id>/merged.parquet` | 7.7 MB, 10 folders | Merged record tables of past SARA-App runs (Parquet). Regression of record/duplicate counts; needs `pyarrow` |

Tests using these files must be marked `@pytest.mark.large` and skip when the file is missing. Their sizes and counts are
in `tests/data/EXPECTED.json` (regenerate with `python scripts/build_expected.py`).

Before publishing the repository: check the licences of `test.zip` and decide about Git LFS.
