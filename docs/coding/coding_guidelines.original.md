# Coding Guidelines

## Readability and documentation

- Write code, identifiers, docstrings, logs, and comments in clear English.
- Add complete type annotations to functions, methods, public attributes, and meaningful local data structures. Prefer concrete types over `Any`; use `Any` only when the external data is genuinely unconstrained and explain that boundary.
- Give each public class and function a docstring that explains its purpose, inputs or invariants, outputs, side effects, and failure behavior where relevant.
- Add comments for non-obvious decisions, validation rules, security constraints, or tricky control flow. Comments should explain why, not paraphrase the next line.
- Keep `docs/` aligned with real behavior. Mark roadmap details as planned, not implemented.

## Domain and module boundaries

- Pydantic models are the validated source of truth for domain data.
- Keep schemas independent of Flet, SQL engines, APIs, and export formats.
- Keep SQL in persistence/search services, not GUI views. Keep UI presentation separate from business rules.
- Validate external input when it enters the application and report invalid data with actionable context.
- Serialize models explicitly at JSON or external API boundaries. Do not pass unvalidated dictionaries through internal APIs in place of domain models.

## Errors and logs

- Fail clearly when required work cannot be completed; do not silently swallow exceptions.
- Catch exceptions at a boundary where the application can add useful context, recover, or return a clear failure status. Re-raise when callers must know the operation failed.
- Use the standard `logging` module. Include operation and safe identifiers/paths, but never log credentials, authorization headers, tokens, private questionnaire responses, or full sensitive payloads.
- Preserve traceback information for unexpected failures with `logger.exception`.
- For API work, document and test timeout, retry, rate-limit, authentication, and partial-failure behavior. Never retry a non-idempotent operation blindly.

## Asynchronous work

- Do not block Flet's event loop with network I/O, file I/O, database calls, or expensive model inference.
- Prefer native async clients. Offload synchronous I/O and CPU-intensive work to an appropriate worker mechanism.
- Keep cancellation, timeouts, and user-visible loading/error state explicit. Do not create detached tasks whose errors are unobserved.

## Testing

- Add focused unit tests for successful behavior, invalid input, boundary values, and important failure paths.
- Use synthetic fixtures and temporary directories; do not use participant data or real credentials in tests.
- Add integration tests when module boundaries, persistence, external APIs, or complete user flows are involved. Mock external services unless a separately controlled test environment is explicitly configured.
- Tests should assert meaningful outcomes and errors, not implementation trivia.
- Run the narrow tests and Ruff checks for every task. Run the broader test suite before merging when the change affects shared behavior.

## Git and review

- Make one focused, descriptive commit after a completed task when the user has authorized commits. The commit message should identify the behavior or deliverable, not merely say “update”.
- Stage only intended files. Review `git diff --cached --name-only` and the staged diff before committing.
- Never commit `.env` files, keys, tokens, private source material, participant data, or production exports. Pushes are performed by the user unless explicitly requested.
- Do not mix unrelated refactors into a feature commit. Document test commands and any remaining limitations in the task summary.
