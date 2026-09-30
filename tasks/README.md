# Backlog (agent task cards)

One file per task. Pick the first task whose dependencies are done. Update the `Status:` line when you finish.

| ID | Milestone | Title | h | Depends on | Status |
|---|---|---|---|---|---|
| [T-M0-01](T-M0-01.md) | M0 | Decide remaining open questions and initialise the repository | 2 | - | todo |
| [T-M0-03](T-M0-03.md) | M0 | Choose and apply the final technical names for Critical Apprais.AI | 3 | T-M0-01 | todo |
| [T-M0-02](T-M0-02.md) | M0 | CI, lint and type-check pipeline | 4 | T-M0-01 | done (review) |
| [T-M1-01](T-M1-01.md) | M1 | Package skeleton, dev setup, CI green | 4 | T-M0-02 | done (review) |
| [T-M1-02](T-M1-02.md) | M1 | Pydantic models for project.yaml + loader with precise errors | 6 | T-M1-01 | done (review) |
| [T-M1-03](T-M1-03.md) | M1 | Workspace: folder layout, schema version, lock with heartbeat, atomic writes | 6 | T-M1-01 | done (review) |
| [T-M1-04](T-M1-04.md) | M1 | Format detection (sniffing) for RIS/NBIB/BibTeX/CSV/XLSX/ZIP | 4 | T-M1-01 | done (review) |
| [T-M1-05](T-M1-05.md) | M1 | RIS reader (continuation lines, headers, type table) | 5 | T-M1-04 | done |
| [T-M1-06](T-M1-06.md) | M1 | NBIB/MEDLINE reader | 4 | T-M1-04 | todo |
| [T-M1-07](T-M1-07.md) | M1 | BibTeX reader (pre-clean, pybtex, tolerant fallback) | 6 | T-M1-04 | todo |
| [T-M1-08](T-M1-08.md) | M1 | Table reader (CSV/TSV/XLSX): encoding, delimiter, column mapping | 5 | T-M1-04 | todo |
| [T-M1-09](T-M1-09.md) | M1 | PDF-ZIP reader with quality flags (DEFERRED: full text is not part of v1) | 4 | T-M1-04 | deferred (ADR 0015 - full text later) |
| [T-M1-10](T-M1-10.md) | M1 | Normalisation and records.csv writer/reader, source hashes, import log | 5 | T-M1-05, T-M1-06, T-M1-07, T-M1-08 | todo |
| [T-M1-11](T-M1-11.md) | M1 | CLI: init, import, status | 3 | T-M1-02, T-M1-03, T-M1-10 | todo |
| [T-M1-12](T-M1-12.md) | M1 | German UI texts (de.yaml) and new i18n keys | 4 | T-M1-01 | done (review) |
| [T-M2-01](T-M2-01.md) | M2 | Deduplication strategies with normalised titles and review list | 6 | T-M1-10 | todo |
| [T-M2-02](T-M2-02.md) | M2 | Optional fuzzy duplicate detection | 4 | T-M2-01 | todo |
| [T-M2-03](T-M2-03.md) | M2 | Missing abstract, NOT_SCREENABLE, retracted and quality flags | 3 | T-M1-10 | todo |
| [T-M2-04](T-M2-04.md) | M2 | Preflight service (codes) and CLI output | 4 | T-M2-03 | todo |
| [T-M2-05](T-M2-05.md) | M2 | Tokenizers per provider and price source; exact estimate with real texts | 6 | T-M1-10 | partially done (estimator ported) |
| [T-M2-06](T-M2-06.md) | M2 | Duration estimate, cost confirmation, `sara check` | 4 | T-M2-04, T-M2-05 | todo |
| [T-M2-07](T-M2-07.md) | M2 | PRISMA events for import and dedup (events.jsonl) | 5 | T-M2-01 | todo |
| [T-M2-08](T-M2-08.md) | M2 | Deterministic pre-filters (language, year, publication type, retracted) | 5 | T-M1-10, T-M2-03 | todo |
| [T-M3-01](T-M3-01.md) | M3 | LLMProvider protocol and MockProvider with scenarios S1-S15 | 8 | T-M1-01 | done (review) |
| [T-M3-02](T-M3-02.md) | M3 | OpenAI-compatible provider (SwissGPT first) and OpenAI provider (chat, usage, error mapping) | 8 | T-M3-01 | todo |
| [T-M3-03](T-M3-03.md) | M3 | Retry/backoff, error classes, circuit breaker | 6 | T-M3-01 | todo |
| [T-M3-04](T-M3-04.md) | M3 | Rate limiter (RPM/TPM) and adaptive concurrency | 8 | T-M3-01 | todo |
| [T-M3-05](T-M3-05.md) | M3 | Prompt builder, YAML prompt variants, prompt hash | 6 | T-M1-02 | todo |
| [T-M3-06](T-M3-06.md) | M3 | Answer schema, parser, consistency rule, quote check, legacy parser | 8 | T-M3-05 | todo |
| [T-M3-07](T-M3-07.md) | M3 | Screening engine (producer, workers, single writer), cost limit, control file | 12 | T-M3-02, T-M3-03, T-M3-04, T-M3-06 | todo |
| [T-M3-08](T-M3-08.md) | M3 | Checkpoint, resume, manifest, run lock | 8 | T-M3-07, T-M1-03 | todo |
| [T-M3-09](T-M3-09.md) | M3 | CLI: screen (--sample, --repeats, --resume, --yes), status | 4 | T-M3-08 | todo |
| [T-M3-10](T-M3-10.md) | M3 | Acceptance tests AT2-AT4 and live smoke test | 4 | T-M3-09 | todo |

Total estimate: 170 h without deferred tasks (33 tasks). Later milestones (M4-M8) follow chapter 21 of the plan and get cards when M3 is done.
