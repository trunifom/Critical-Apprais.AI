# AGENTS.md - instructions for AI coding agents (project: Critical Apprais.AI)

This file is the entry point for any AI coding agent (Claude Code, Codex, Copilot, Cursor, ...). Read it fully, then
open `docs/INDEX.md`. Human readers: see `README.md`.

## 1. What this project is

**The product you are building is called "Critical Apprais.AI".** It is **not** SARA. A software called **SARA** existed before (a research prototype and a Streamlit/Supabase web app, `SARA-App`, from a ZHAW project); it is the *predecessor*. Critical Apprais.AI is a new, local software with the same professional goal. Read `docs/NAMING_AND_HISTORY.md` now.

Naming rules (binding):
- Write the product name exactly **Critical Apprais.AI**; use `saralocal.branding.PRODUCT_NAME` in user-visible strings.
- Never call the new product "SARA" in UI texts, reports, manifests or new documents. "SARA", "SARA-App" and `reference/` describe the predecessor and are allowed only in historical/reference contexts.
- The folder `SARA-Local`, the Python package `saralocal`, the CLI command `sara` and the state folder `.sara/` are **provisional working names** created before the name was chosen. Keep them until task `T-M0-03` renames them; do not rename on your own.

**Critical Apprais.AI** is a local Python tool for systematic literature reviews. It imports bibliographic exports
(RIS, NBIB/MEDLINE, BibTeX, CSV/XLSX, ZIP of PDFs), prepares the records (normalise, mark duplicates, mark missing
abstracts), sends each record together with the inclusion/exclusion criteria to an LLM over an API, and writes the
decisions (with per-criterion verdicts and short justifications) into tables (CSV/XLSX) in a project folder.

- **No database, no server, no accounts.** The project folder is the database.
- It succeeds the predecessor `SARA-App` (Streamlit + Supabase + background worker). The predecessor's code is in
  `reference/` as a **read-only snapshot**. The specification is `docs/PROJEKTPLAN.md`.
- Results are *proposals for human review*, never final decisions.

## 2. Where things are

| Path | What | Rule |
|---|---|---|
| `docs/PROJEKTPLAN.md` | Full specification (German, chapters 1-40) | Source of truth for behaviour and formats. Use `python scripts/plan_chapter.py <n>` to print one chapter |
| `docs/INDEX.md` | Map of all documents and a reading plan per task | Start here |
| `docs/KICKOFF_PROMPT.md` | Start-Prompt with phases A-C (orientation, git setup + first commit, task loop) | Follow when starting |
| `docs/NAMING_AND_HISTORY.md` | Product name, predecessor SARA, naming rules, provisional identifiers | Read first |
| `docs/MIGRATION.md` | Which old file becomes which new module, and its status | Update when you port something |
| `docs/coding/coding_guidelines.md` | Coding rules | Binding |
| `docs/adr/` | Architecture decision records | Add one when you make a structural decision |
| `docs/swissgpt/`, `docs/literature/`, `docs/guidelines/`, `docs/reports/` | API spec, papers, PRISMA/PICO guidance, project report | Read-only background |
| `docs/legacy/` | Old manuals from earlier repositories | Partly outdated, see `docs/INDEX.md` |
| `src/saralocal/` | The new code base | Your work goes here |
| `tests/unit`, `tests/integration` | Tests | Every change needs tests |
| `tests/data/` | Small fixtures (public bibliographic exports) + `EXPECTED.json` (oracle counts) | Read-only |
| `tests/data_large/` | Big fixtures (11.5 MB BibTeX, PDF ZIP, PRISMA snapshots), not versioned | Optional, mark tests `large` |
| `tests/legacy_runs/`, `tests/expected/` | Archived SARA-App runs and their statistic reports (golden files) | Read-only |
| `reference/sara-app/`, `reference/sara-ancestor/` | Old code, unchanged | **Never edit. Never import.** Copy into `src/` and adapt, leaving a `PORTED from` header |
| `templates/` | Example `project.yaml`, model catalog, price table, prompt variants | Data, not code |
| `tasks/` | Task cards (backlog) | Pick the first open card whose dependencies are done |
| `assets/` | Lottie animations, architecture drawing | Optional |
| `scripts/` | Helper scripts | |

## 3. How to work

0. Read `docs/UMSETZUNGSPLAN_UND_FORTSCHRITT.md` (progress log, next step) and keep it current: after each tested function commit, then tick the line with date, time and commit hash.
1. Read `docs/INDEX.md`, then the task card in `tasks/` (it names the plan chapters and the files to reuse).
2. Read only the plan chapters the card lists (the plan is large). Search with `grep -n "^## " docs/PROJEKTPLAN.md`.
3. Look at `reference/` and `docs/MIGRATION.md` **before writing code**: part of the work may already be done or
   reusable. Mind the known defects listed in plan chapter 3 (L1-L18); do not copy the defective behaviour.
4. Write the test first or together with the code. Use fixtures from `tests/data/`. Compare with `EXPECTED.json`.
5. Run `python -m pytest -q` and `python -m ruff check .` (install with `pip install -e ".[dev]"`).
6. Update the card's `Status:` line, `docs/MIGRATION.md` (if you ported something) and the docs you touched.
7. Do not commit unless the user asked you to. Never push.

Setup on Windows (PowerShell):

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m pytest -q
```

## 4. Golden rules (violating these is a defect)

1. **Never turn an unusable model answer into a label.** Empty, malformed, truncated or refused answers get a status
   (`parse_error`, `truncated`, `api_error`), never `INCLUDE`. (Old code did the opposite: lesson L4.)
2. **Key everything by `study_uid`**, never by row position. Every result row carries its `study_uid` from creation.
3. **Non-destructive data handling.** Duplicates and records without abstract are *marked* with a reason, never deleted.
4. **Persisted names are a contract**: column names, enum values, JSON keys, file names (plan chapters 25-26). Changing
   one needs a schema version bump and a migration.
5. **No secrets in files.** API keys only via environment variable or OS key store. Never log keys, headers, abstracts.
6. **Append-only checkpointing** for screening results (`screening.jsonl`), exactly one writer task, flush per line.
7. **The core does not import** a GUI framework, `typer`, or an LLM SDK. Talk to the outside only through ports.
8. **No live API calls in tests** unless marked `@pytest.mark.live`. Use `MockProvider`.
9. **Reproducibility**: store seeds, prompt hash, model returned by the provider, software version in the run manifest.
10. **Do not invent facts.** Model names, prices, limits and API parameters must be verified against the provider
    documentation; put unverified values in data files with `null`, not in code.

## 5. Conventions

- Python >= 3.11, type hints everywhere, docstrings on public API, `logging` instead of `print`, `pathlib.Path`.
- Code/docstrings/logs/comments in English. Documents in `docs/` in German (Swiss spelling: "ss").
- Text files UTF-8; Excel exports UTF-8 with BOM; CSV dialect and JSONL rules in plan chapter 25.7.
- All user-visible text lives in `src/saralocal/i18n/texts/*.yaml` (en, de). Errors have a code (plan chapter 26.4).
- Ruff line length 100. Files ported verbatim keep their style until a task refactors them (see `pyproject.toml`).
- Prefer small, focused modules; follow the layering in plan chapter 28.2.

## 6. Definition of done (per task)

- [ ] Acceptance criteria of the task card met
- [ ] Type hints + docstrings; `ruff` clean; no new warnings in the log
- [ ] Unit tests (and integration tests where modules meet) written and green; failure paths covered
- [ ] Golden/oracle checks used where a legacy result or `EXPECTED.json` value exists
- [ ] User-visible strings in i18n (en + de), errors with codes
- [ ] Docs updated (`docs/MIGRATION.md`, chapter of the plan if behaviour changed, ADR if structural)
- [ ] Card status updated; short summary of what changed, how tested, known limits

## 7. Things to ask the user before doing

- Adding a dependency that is not listed in `pyproject.toml` extras.
- Changing the storage format or the persisted names (GUI framework is decided: Streamlit).
- Anything that sends data to an external service, deletes files outside your own temp files, or commits/pushes.
- Using the large third-party PDFs in `docs/` beyond reading them.

## 8. Decisions already made by the user (do not re-open)

- GUI: **Streamlit** (ADR 0013). Core and CLI stay GUI-independent.
- **Version 1 = title/abstract screening only.** Full-text screening comes later (ADR 0015); reject `mode: fulltext` with a clear message.
- Main provider will be **SwissGPT** via the OpenAI-compatible API (ADR 0014). It has no `response_format` and no `seed`: always validate answers in code.
- Only open-access PDFs will ever be uploaded (later); licence questions are considered non-critical by the user.

## 9. Known state at handover

- The handover state (47 tests, four ported modules) is history. Milestone A is reached: config, project folder, format detection,
  readers (RIS, NBIB, BibTeX, tables), normalisation, `records.csv`, import log, `sara init/import/status`, German + English texts.
- Current state, test count and the next step: `docs/UMSETZUNGSPLAN_UND_FORTSCHRITT.md` (keep it current, it is the hand-over log).
- Documentation set to maintain with every task: `docs/BENUTZERHANDBUCH.md`, `docs/ENTWICKLERDOKUMENTATION.md`, `docs/ARCHITEKTUR.md`,
  `README.md`, `CHANGELOG.md` (tests/unit/test_docs.py checks that they stay consistent with the code).
