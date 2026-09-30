"""Generate tasks/*.md from the table below (source of truth for the backlog structure).

Run: python scripts/generate_task_cards.py
Edit the TASKS list, re-run, then commit both the script and the generated cards.
Statuses are edited by hand in the generated cards (line "Status:") - re-running overwrites them,
so only re-run when you intentionally reset the backlog.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tasks"

PLAN = "docs/PROJEKTPLAN.md"

# id, title, hours, depends, plan chapters, reuse (existing files), deliverables, acceptance, status
TASKS: list[dict] = [
    dict(id="T-M0-01", ms="M0", title="Decide remaining open questions and initialise the repository", h=2, dep=[],
         plan="23, 39", reuse=["docs/PROJEKTPLAN.md chapter 39 (decisions)"],
         out=["git repository initialised, first commit (only if the user authorises)", "LICENSE for the code chosen"],
         acc=["Already decided (do not re-open): Streamlit (ADR 0013), no full text in v1 (ADR 0015), SwissGPT as expected main provider (ADR 0014)",
              "Remote/owner of the repository decided and authentication solved (token or SSH)",
              "Decision on whether third-party PDFs and PubMed author e-mails stay in a public repo (Git LFS, exclude or private repo)"],
         status="todo"),
    dict(id="T-M0-03", ms="M0", title="Choose and apply the final technical names for Critical Apprais.AI", h=3, dep=["T-M0-01"],
         plan="15, 16, 17 and docs/NAMING_AND_HISTORY.md", reuse=["docs/NAMING_AND_HISTORY.md (options in section 4)", "src/crapai/branding.py"],
         out=["Decision record docs/adr/0016-technical-names.md", "Renamed folder/repository, Python package, project name in pyproject.toml, CLI command, state folder",
              "All imports, tests, docs, task cards and templates updated consistently; docs/NAMING_AND_HISTORY.md section 4 rewritten"],
         acc=["`python -m pytest -q` is green after the rename", "No occurrence of the old working names (`saralocal`, `sara ` CLI, `.sara/`) remains except in historical contexts",
              "The product name in every user-visible string comes from `PRODUCT_NAME`", "The predecessor names SARA/SARA-App appear only in historical/reference/legacy contexts"],
         status="todo"),
    dict(id="T-M0-02", ms="M0", title="CI, lint and type-check pipeline", h=4, dep=["T-M0-01"],
         plan="18, 33.8", reuse=["pyproject.toml"],
         out=[".github/workflows/ci.yml", "ruff + mypy configuration confirmed", "import-linter contract for the layering rules"],
         acc=["CI runs pytest on Windows, Linux, macOS (Python 3.11-3.13)", "`python -m ruff check .` is clean",
              "Layer contract test fails if core imports a GUI framework or an LLM SDK"],
         status="todo"),
    dict(id="T-M1-01", ms="M1", title="Package skeleton, dev setup, CI green", h=4, dep=["T-M0-02"],
         plan="17", reuse=["pyproject.toml", "src/crapai/ (already contains 4 ported modules)"],
         out=["src/crapai/{project,io,prisma,screening,llm,prompts,stats,services}/__init__.py", "README quick start"],
         acc=["`pip install -e .[dev]` works on Windows", "`python -m pytest -q` passes (45 tests at handover)"],
         status="partially done (skeleton + 4 ported modules exist)"),
    dict(id="T-M1-02", ms="M1", title="Pydantic models for project.yaml + loader with precise errors", h=6, dep=["T-M1-01"],
         plan="16, 26.4", reuse=["templates/project.example.yaml", "src/crapai/criteria/template.py", "src/crapai/enums.py"],
         out=["src/crapai/config/models.py", "src/crapai/config/loader.py", "tests/unit/test_config.py"],
         acc=["templates/project.example.yaml validates", "Error message names the YAML path and reason (E2xx)",
              "Precedence CLI > env > project.yaml > user config > defaults implemented (16.3)",
              "API keys can never be stored in the model (only `api_key_env`)"],
         status="todo"),
    dict(id="T-M1-03", ms="M1", title="Workspace: folder layout, schema version, lock with heartbeat, atomic writes", h=6, dep=["T-M1-01"],
         plan="6, 11, 28.9", reuse=[], out=["src/crapai/project/{workspace,lock,atomic}.py", "tests/unit/test_workspace.py"],
         acc=["Folder layout of chapter 6 is created", "Second lock holder is refused; stale lock (heartbeat > 60 s, dead PID) can be taken over",
              "`os.replace` retry on PermissionError (5 x 200 ms) then alternative file name",
              "Kill test: half-written temp file never replaces the real file"],
         status="todo"),
    dict(id="T-M1-04", ms="M1", title="Format detection (sniffing) for RIS/NBIB/BibTeX/CSV/XLSX/ZIP", h=4, dep=["T-M1-01"],
         plan="25.1, 25.9", reuse=["reference/sara-app/core/file_handler.py (_detect_file_type, _read_text)", "tests/data/*"],
         out=["src/crapai/io/readers/detect.py", "tests/unit/test_detect.py"],
         acc=["`pubmed-adhd-set.ris` is detected as NBIB", "`example_AB_nr4.txt` is detected as RIS",
              "Result carries type, confidence and reason", "Decision uses content first, extension second"],
         status="todo"),
    dict(id="T-M1-05", ms="M1", title="RIS reader (continuation lines, headers, type table)", h=5, dep=["T-M1-04"],
         plan="25.2", reuse=["reference/sara-app/core/file_handler.py (_parse_ris) - has bug L15, do not copy the tag filter"],
         out=["src/crapai/io/readers/ris.py", "tests/unit/test_ris_reader.py"],
         acc=["`pubmed_adhd_converted-zotero.ris`: 706 records, 156 with abstract, multi-line abstracts complete (129 continuation lines joined)",
              "`citation-export.ris`: 6 records, `Record #` header lines skipped", "`IEEE-Xplore_SR_2023-2024.ris`: 46 records, EP/VO mapped",
              "Unknown tags end up in extra_json; nothing is lost", "Counts equal tests/data/EXPECTED.json"],
         status="todo"),
    dict(id="T-M1-06", ms="M1", title="NBIB/MEDLINE reader", h=4, dep=["T-M1-04"],
         plan="25.3", reuse=["reference/sara-app/core/file_handler.py (_parse_nbib, _parse_nbib_block, helper functions)"],
         out=["src/crapai/io/readers/nbib.py", "tests/unit/test_nbib_reader.py"],
         acc=["`pubmed-adhd-set.nbib`: 100 records, `pubmed-adhdANDchi-set.nbib`: 62 records",
              "DOI from `LID`/`AID` with `[doi]` marker", "`is_retracted` from publication types", "PT/MH/OT kept as lists/columns"],
         status="todo"),
    dict(id="T-M1-07", ms="M1", title="BibTeX reader (pre-clean, pybtex, tolerant fallback)", h=6, dep=["T-M1-04"],
         plan="25.4", reuse=["reference/sara-app/core/file_handler.py (_parse_bib_*, clean_latex)"],
         out=["src/crapai/io/readers/bibtex.py", "tests/unit/test_bibtex_reader.py"],
         acc=["`citation-export.bib`: 48 entries despite `Record #k of n` lines", "`pubmed_adhd_converted-zotero.bib`: 706 entries",
              "`data_large/citation-export_2.bib` (11.5 MB, 1343 entries) imports within a fixed time limit (marker `large`)",
              "No file is written into the working directory (bibReader path is dropped)"],
         status="todo"),
    dict(id="T-M1-08", ms="M1", title="Table reader (CSV/TSV/XLSX): encoding, delimiter, column mapping", h=5, dep=["T-M1-04"],
         plan="25.5", reuse=["src/crapai/legacy.py (encoding fallback chain)"],
         out=["src/crapai/io/readers/tabular.py", "tests/unit/test_tabular_reader.py"],
         acc=["cp1252 and UTF-8 files read; encoding logged", "Semicolon and comma delimiters detected", "PMID/DOI stay text",
              "`--map abstract=<col>` supported and stored for repeatability"],
         status="todo"),
    dict(id="T-M1-09", ms="M1", title="PDF-ZIP reader with quality flags (DEFERRED: full text is not part of v1)", h=4, dep=["T-M1-04"],
         plan="25.6", reuse=["reference/sara-app/utils/helpers.py (extract_text_from_pdf_bytes)", "reference/sara-app/core/preflight.py (zip filter)"],
         out=["src/crapai/io/readers/pdf_zip.py", "tests/unit/test_pdf_zip_reader.py"],
         acc=["`data_large/test.zip`: 6 PDFs found, 6 `__MACOSX` entries ignored, nothing extracted to disk",
              "Flags: pages, chars, has_text_layer; NO_TEXT and ENCRYPTED handled"],
         status="deferred (ADR 0015 - full text later)"),
    dict(id="T-M1-10", ms="M1", title="Normalisation and records.csv writer/reader, source hashes, import log", h=5, dep=["T-M1-05", "T-M1-06", "T-M1-07", "T-M1-08"],
         plan="7, 8.2, 8.3, 25.7, 26.1", reuse=["reference/sara-app/core/file_handler.py (_normalize)", "reference/sara-app/core/literature_database.py (_ensure_status_columns)"],
         out=["src/crapai/io/normalize.py", "src/crapai/io/records_store.py", "tests/unit/test_records_store.py"],
         acc=["Column order and types exactly as in chapter 26.1", "Property test: write -> read is lossless for arbitrary Unicode text, commas, quotes, newlines",
              "SHA-256 of each source file stored; re-import of the same hash is detected (E106)"],
         status="todo"),
    dict(id="T-M1-11", ms="M1", title="CLI: init, import, status", h=3, dep=["T-M1-02", "T-M1-03", "T-M1-10"],
         plan="15.1, 27.10", reuse=[], out=["src/crapai/cli.py", "tests/unit/test_cli_basic.py"],
         acc=["`crapai init demo --from-template demo` creates a project", "`crapai import demo tests/data/example_db_nr2_total-10_duplicates-3.ris --label A` writes 10 records",
              "Exit codes as in chapter 15.1"],
         status="todo"),
    dict(id="T-M1-12", ms="M1", title="German UI texts (de.yaml) and new i18n keys", h=4, dep=["T-M1-01"],
         plan="27.7", reuse=["src/crapai/i18n/texts/en.yaml", "reference/sara-app/texts/en.yaml"],
         out=["src/crapai/i18n/texts/de.yaml", "extended en.yaml (run.*, results.*, prisma.*, evaluation.*, errors.<code>.*)"],
         acc=["Test: every key required by the UI exists in en and de", "Swiss spelling (ss)", "Error texts follow 'what happened - why - what to do'"],
         status="todo"),
    dict(id="T-M2-01", ms="M2", title="Deduplication strategies with normalised titles and review list", h=6, dep=["T-M1-10"],
         plan="8.4", reuse=["reference/sara-app/core/literature_database.py (mark_duplicates)", "reference/sara-app/core/prisma_workflow.py (DedupConfig)"],
         out=["src/crapai/prisma/dedup.py", "tests/unit/test_dedup.py"],
         acc=["`example_db_nr2...`: 10 records, 3 duplicates; `nr3`: 8 records, 2 duplicates", "Merged trio: 31 records, 13 unique DOIs, 18 duplicates (EXPECTED.json)",
              "Non-destructive: `duplicate_of` points to the kept record; row count unchanged",
              "Helpers duplicated in the old code (_ensure_status_columns etc.) exist once"],
         status="todo"),
    dict(id="T-M2-02", ms="M2", title="Optional fuzzy duplicate detection", h=4, dep=["T-M2-01"],
         plan="8.4, 28.10", reuse=[], out=["src/crapai/prisma/dedup_fuzzy.py", "reports/possible_duplicates.csv writer"],
         acc=["Blocking keeps runtime near-linear on 706 records", "Fuzzy hits are only *suggested* (POSSIBLE_DUPLICATE), never auto-excluded"],
         status="todo"),
    dict(id="T-M2-03", ms="M2", title="Missing abstract, NOT_SCREENABLE, retracted and quality flags", h=3, dep=["T-M1-10"],
         plan="8.4, 26.3", reuse=["reference/sara-app/core/literature_database.py (mark_missing_abstracts)"],
         out=["src/crapai/prisma/validity.py", "tests/unit/test_validity.py"],
         acc=["zotero RIS: about 550 of 706 records flagged NO_ABSTRACT (706 records, 156 AB tags), , CHAP 'Front-matter' flagged", "abstract_suspect_concat flag on the Cochrane BibTeX example"],
         status="todo"),
    dict(id="T-M2-04", ms="M2", title="Preflight service (codes) and CLI output", h=4, dep=["T-M2-03"],
         plan="8.5", reuse=["reference/sara-app/core/preflight.py", "src/crapai/enums.py (PreflightStatus/IssueCode)"],
         out=["src/crapai/services/preflight.py", "tests/unit/test_preflight.py"],
         acc=["Warning below 60 % abstract coverage; error when zero abstracts in abstract mode", "No Streamlit UploadedFile dependency (paths only)"],
         status="todo"),
    dict(id="T-M2-05", ms="M2", title="Tokenizers per provider and price source; exact estimate with real texts", h=6, dep=["T-M1-10"],
         plan="8.5, 29.4", reuse=["src/crapai/cost/estimator.py (ported, tested)", "templates/pricing.example.csv"],
         out=["src/crapai/cost/tokenizers.py", "extended estimator", "tests/unit/test_estimator_real_texts.py"],
         acc=["Estimate uses actual title+abstract token counts, not a sample", "Unknown model -> tokens only, no cost", "Fulltext no longer uses the fixed 450*12 token guess"],
         status="partially done (estimator ported)"),
    dict(id="T-M2-06", ms="M2", title="Duration estimate, cost confirmation, `crapai check`", h=4, dep=["T-M2-04", "T-M2-05"],
         plan="8.5, 15.1", reuse=[], out=["CLI command `check`", "tests"],
         acc=["Shows records, duplicates, no-abstract, LLM-eligible, tokens, cost band, duration", "`--yes` required to start a run without a terminal"],
         status="todo"),
    dict(id="T-M2-07", ms="M2", title="PRISMA events for import and dedup (events.jsonl)", h=5, dep=["T-M2-01"],
         plan="12.2", reuse=["reference/sara-app/core/prisma_logger.py (event model, to_prisma_flow, validate_rollup) - drop the Supabase methods"],
         out=["src/crapai/prisma/events.py", "src/crapai/prisma/flow.py", "tests/unit/test_prisma_flow.py"],
         acc=["Flow numbers reproduce the arithmetic of `to_prisma_flow` for both duplicate reporting modes", "No network or database import in the module"],
         status="todo"),
    dict(id="T-M2-08", ms="M2", title="Deterministic pre-filters (language, year, publication type, retracted)", h=5, dep=["T-M1-10", "T-M2-03"],
         plan="35.4 (U3), 8.4, 26.3", reuse=["src/crapai/enums.py", "records.csv columns language/year/publication_types/is_retracted (plan 26.1)"],
         out=["src/crapai/prisma/prefilters.py", "prefilters block in project.yaml models (T-M1-02)", "tests/unit/test_prefilters.py"],
         acc=["Filters run in code BEFORE the LLM and never consume tokens", "Excluded records keep a reason code (PREFILTER_LANGUAGE, PREFILTER_YEAR, PREFILTER_TYPE, RETRACTED) and stay visible",
              "`on_missing: pass` sends records with unknown language/year to the LLM instead of dropping them", "Counts appear in the PRISMA flow as 'removed before screening (other)'"],
         status="todo"),
    dict(id="T-M3-01", ms="M3", title="LLMProvider protocol and MockProvider with scenarios S1-S15", h=8, dep=["T-M1-01"],
         plan="9.1, 28.3, 33.2", reuse=["reference/sara-ancestor/tools/llm_providers.py (BaseProvider idea)", "reference/sara-ancestor/tests_unit/test_inference.py (mocking pattern)"],
         out=["src/crapai/llm/base.py", "src/crapai/llm/mock_provider.py", "tests/unit/test_mock_provider.py"],
         acc=["All 15 scenarios of chapter 33.2 can be selected by name and are deterministic (seeded)"], status="todo"),
    dict(id="T-M3-02", ms="M3", title="OpenAI-compatible provider (SwissGPT first) and OpenAI provider (chat, usage, error mapping)", h=8, dep=["T-M3-01"],
         plan="9.2, 29.3", reuse=["reference/sara-ancestor/tools/llm_providers.py (OpenAIProvider, SwissGPTProvider)", "docs/swissgpt/Documentation_API_SwissGPT-AlpineAI.json",
                                 "templates/models.yaml"],
         out=["src/crapai/llm/openai_provider.py", "src/crapai/llm/compatible_provider.py", "tests with respx mocks"],
         acc=["Temperature/top_p/seed/max tokens come from configuration (ancestor hard-coded 0.2/0.9/1024)", "HTTP 429/5xx/timeouts/401 map to the exception classes of 28.7",
              "SwissGPT (main provider, ADR 0014): works without response_format/seed; answers validated in code; models via GET /v1/models", "One live smoke test marked `live`"],
         status="todo"),
    dict(id="T-M3-03", ms="M3", title="Retry/backoff, error classes, circuit breaker", h=6, dep=["T-M3-01"],
         plan="9.4", reuse=[], out=["src/crapai/llm/retry.py", "tests"],
         acc=["Retries actually happen (contrast with lesson L2)", "401/403 stops the run; 400 context-too-long is not retried", "Circuit breaker pauses after N consecutive failures"],
         status="todo"),
    dict(id="T-M3-04", ms="M3", title="Rate limiter (RPM/TPM) and adaptive concurrency", h=8, dep=["T-M3-01"],
         plan="9.3", reuse=["reference/sara-app/core/model_query.py (_batch_inference_with_token_limit - idea only)"],
         out=["src/crapai/llm/ratelimit.py", "tests"],
         acc=["Given RPM/TPM the limiter never exceeds them (simulated clock)", "429 with retry-after halves concurrency, recovers after a clean phase"],
         status="todo"),
    dict(id="T-M3-05", ms="M3", title="Prompt builder, YAML prompt variants, prompt hash", h=6, dep=["T-M1-02"],
         plan="10.1, 10.2", reuse=["templates/prompts/*.yaml", "reference/sara-app/core/prompt_engine.py", "src/crapai/criteria/template.py"],
         out=["src/crapai/prompts/builder.py", "tests/unit/test_prompt_builder.py"],
         acc=["Record text is delimited and treated as data (injection guard sentence present)", "Same input -> same hash; changing one word changes the hash",
              "Fulltext prompt does not repeat criteria unless configured"],
         status="todo"),
    dict(id="T-M3-06", ms="M3", title="Answer schema, parser, consistency rule, quote check, legacy parser", h=8, dep=["T-M3-05"],
         plan="10.3-10.5, 26.2", reuse=["reference/sara-app/core/model_query.py (response_to_dataframe - legacy semantics only)"],
         out=["src/crapai/screening/{schema,parser,consistency}.py", "tests"],
         acc=["Malformed, empty or truncated answers -> parse_error, NEVER label 1 (AT4)", "`consistent=false` when verdicts and decision disagree",
              "Quote not found in abstract -> quote_unverified", "Legacy parser: XXX -> 0, YYY -> 1, anything else -> parse_error"],
         status="todo"),
    dict(id="T-M3-07", ms="M3", title="Screening engine (producer, workers, single writer), cost limit, control file", h=12, dep=["T-M3-02", "T-M3-03", "T-M3-04", "T-M3-06"],
         plan="8.6, 28.4", reuse=["reference/sara-app/core/review_worker.py (orchestration steps, for orientation)"],
         out=["src/crapai/screening/engine.py", "tests/integration/test_engine_mock.py"],
         acc=["Queue is bounded (backpressure)", "pause/stop via control.json within 2 s", "max_cost stops the run cleanly", "Exactly one task appends to screening.jsonl"],
         status="todo"),
    dict(id="T-M3-08", ms="M3", title="Checkpoint, resume, manifest, run lock", h=8, dep=["T-M3-07", "T-M1-03"],
         plan="7.2, 11, 12.1", reuse=[], out=["src/crapai/screening/checkpoint.py", "src/crapai/project/manifest.py", "tests"],
         acc=["AT3: kill at 50 %, resume -> every study_uid has exactly one ok row, result equals an undisturbed run", "Half-written last JSONL line is truncated on resume",
              "Resume with changed criteria/prompt/model hash is refused (no mixed runs)"],
         status="todo"),
    dict(id="T-M3-09", ms="M3", title="CLI: screen (--sample, --repeats, --resume, --yes), status", h=4, dep=["T-M3-08"],
         plan="15.1, 27.10", reuse=[], out=["CLI commands", "tests"], acc=["Progress line with counters, cost, errors, ETA", "Exit code 3 for interrupted run"], status="todo"),
    dict(id="T-M3-10", ms="M3", title="Acceptance tests AT2-AT4 and live smoke test", h=4, dep=["T-M3-09"],
         plan="18.2, 33", reuse=[], out=["tests/integration/test_acceptance.py"], acc=["AT2, AT3, AT4 automated with the mock provider", "Live smoke test documented and skipped by default"],
         status="todo"),
]


def render(task: dict) -> str:
    def bullets(items: list[str]) -> str:
        return "\n".join(f"- {i}" for i in items) if items else "- (none)"

    plan_refs = ", ".join(f"chapter {c.strip()}" for c in task["plan"].split(","))
    return f"""# {task['id']} - {task['title']}

Milestone: {task['ms']} | Estimate: {task['h']} h | Depends on: {', '.join(task['dep']) or 'nothing'}
Status: {task['status']}

## Read first
- `AGENTS.md` (rules), `docs/INDEX.md` (map)
- `{PLAN}`: {plan_refs}

## Reuse (existing material)
{bullets(task['reuse'])}

## Deliverables
{bullets(task['out'])}

## Acceptance criteria
{bullets(task['acc'])}

## Definition of done
See `AGENTS.md` section "Definition of done" (types, docstrings, tests, ruff, docs, i18n, error codes).
"""


def main() -> None:
    OUT.mkdir(exist_ok=True)
    lines = ["# Backlog (agent task cards)\n",
             "One file per task. Pick the first task whose dependencies are done. Update the `Status:` line when you finish.\n",
             "| ID | Milestone | Title | h | Depends on | Status |", "|---|---|---|---|---|---|"]
    for t in TASKS:
        (OUT / f"{t['id']}.md").write_text(render(t), encoding="utf-8", newline="\n")
        lines.append(f"| [{t['id']}]({t['id']}.md) | {t['ms']} | {t['title']} | {t['h']} | {', '.join(t['dep']) or '-'} | {t['status']} |")
    total = sum(t["h"] for t in TASKS if not t["status"].startswith("deferred"))
    lines.append(f"\nTotal estimate: {total} h without deferred tasks ({len(TASKS)} tasks). Later milestones (M4-M8) follow chapter 21 of the plan and get cards when M3 is done.\n")
    (OUT / "README.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print(f"wrote {len(TASKS)} cards, {total} h")


if __name__ == "__main__":
    main()
