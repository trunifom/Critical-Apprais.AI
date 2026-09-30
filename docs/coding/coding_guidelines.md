# Coding Guidelines (Critical Apprais.AI)

Adapted from `coding_guidelines.original.md` (SARA predecessor repository). The original assumed a Flet GUI,
SQL persistence and questionnaire/participant data. Critical Apprais.AI has **no database** and uses **Streamlit** for the GUI (ADR 0013;
see `docs/PROJEKTPLAN.md` chapters 27 and 39). What changed is listed at the end of this file.

## Readability and documentation

- Write code, identifiers, docstrings, logs, and comments in clear English. Project documents in `docs/` are German
  (Swiss spelling, "ss" instead of "ß") unless a file says otherwise.
- Add complete type annotations to functions, methods, public attributes, and meaningful local data structures.
  Prefer concrete types over `Any`; use `Any` only when external data is genuinely unconstrained and explain that boundary.
- Give each public class and function a docstring that explains its purpose, inputs or invariants, outputs, side effects,
  and failure behavior where relevant.
- Add comments for non-obvious decisions, validation rules, security constraints, or tricky control flow. Comments
  explain *why*, not what the next line does.
- Keep `docs/` aligned with real behavior. Mark roadmap details as *planned*, not implemented.
- Files copied from `reference/` keep a header `PORTED from ...` naming the original and the changes.
- The product is called "Critical Apprais.AI", never "SARA" (docs/NAMING_AND_HISTORY.md). Use `saralocal.branding.PRODUCT_NAME` in user-visible strings.

## Domain and module boundaries

- Pydantic models are the validated source of truth for domain data (project configuration, run manifest,
  screening rows, events).
- Layering (plan chapter 28.2): UI/CLI -> services -> core -> ports -> adapters. The core imports neither a GUI framework,
  `typer`, nor an LLM SDK. Enforce with an import-linter test.
- Keep file-format details (RIS/BibTeX/CSV/XLSX/JSONL) in `io/` readers and writers, not in services or UI code.
- Keep UI presentation separate from business rules. UI code reads project files; long-running work runs in a separate
  worker process (plan chapter 28.4).
- Validate external input when it enters the application and report invalid data with actionable context (error code
  from plan chapter 26.4).
- Serialize models explicitly at JSON/CSV/API boundaries. Do not pass unvalidated dictionaries through internal APIs
  in place of domain models.
- Persisted values (enum values, column names, JSON keys, file names) are a public contract. Changing them requires a
  schema version bump, a migration and a changelog entry.

## Errors and logs

- Fail clearly when required work cannot be completed; do not silently swallow exceptions.
- Raise `SaraError` subclasses (plan chapter 28.7) from the core. Catch exceptions at a boundary (CLI command, worker
  loop, UI handler) where useful context can be added or recovery is possible. Re-raise when callers must know.
- **Never turn an unusable model answer into a label.** A missing or malformed decision is an error status
  (`parse_error`), never "include" (lesson L4 in the plan).
- Use the standard `logging` module. Include operation and safe identifiers/paths (`run_id`, `study_uid`), but never log
  credentials, authorization headers, API keys, abstracts or full payloads (unless the user explicitly enabled
  content logging).
- Preserve traceback information for unexpected failures with `logger.exception`.
- For API work, document and test timeout, retry, rate-limit, authentication, and partial-failure behavior. Never retry a
  non-idempotent operation blindly; a screening call is idempotent per `(run_id, study_uid)`.

## Asynchronous work

- Do not block the event loop with network I/O, file I/O, PDF extraction, or expensive computation. Prefer native async
  clients; offload synchronous or CPU-heavy work to a thread/process executor.
- Keep cancellation, timeouts, and user-visible progress/error state explicit. Do not create detached tasks whose errors
  are unobserved. Exactly one task writes to `screening.jsonl`.

## Files and persistence

- The project folder is the database (plan chapters 6 and 25). Write whole files atomically (temp file + `os.replace`);
  append-only logs are flushed after each line.
- All text files are UTF-8, LF internally. Exports for Excel use UTF-8 with BOM.
- Never modify `sources/` files. Never modify anything under `reference/`.
- Time is stored with time zone (ISO 8601); randomness always with a stored seed.

## Testing

- Add focused unit tests for successful behavior, invalid input, boundary values, and important failure paths.
- Use synthetic or archived fixtures from `tests/data/` and temporary directories (`tmp_path`). Do not use participant
  data, personal data or real credentials in tests. The bibliographic fixtures come from public database exports.
- Mock the LLM (`MockProvider`); tests marked `@pytest.mark.live` may call real APIs, cost money and are never run in CI.
- Add integration tests when module boundaries, persistence, external APIs, or complete user flows are involved.
- Tests assert meaningful outcomes and errors, not implementation trivia. Where a legacy result exists (`tests/expected/`),
  prefer a golden test against it (see `tests/unit/test_legacy_golden.py`).
- Run the narrow tests and Ruff checks for every task. Run the whole suite before finishing a task that changes shared
  behavior: `python -m pytest -q` and `python -m ruff check .`.

## Git and review

- Make one focused, descriptive commit after a completed task **when the user has authorized commits**. The commit message
  identifies the behavior or deliverable, not merely "update".
- Stage only intended files. Review `git diff --cached --name-only` and the staged diff before committing.
- Never commit `.env` files, keys, tokens, private source material, participant data, or production exports. Pushes are
  performed by the user unless explicitly requested.
- Do not mix unrelated refactors into a feature commit. Document test commands and remaining limitations in the task summary.

## What changed compared with the original guidelines

| Original | Now | Why |
|---|---|---|
| "Keep schemas independent of Flet, SQL engines, APIs, and export formats" | independent of *any GUI framework*, file formats and LLM APIs | No SQL in SARA-Local; the GUI is Streamlit (kept out of the core) |
| "Keep SQL in persistence/search services" | removed; new section *Files and persistence* | Project folder replaces the database |
| "Do not block Flet's event loop" | "Do not block the event loop" | GUI-neutral; matters for asyncio worker and any GUI |
| "private questionnaire responses" in the log rule | "abstracts and payloads" | Different sensitive data in this project |
| Test rule "participant data" | archived public bibliographic exports and legacy run CSVs | Fixtures of this project |
| (none) | Rule about never mapping unusable model output to a label; persisted values are a contract | Lessons L4, L1 |
