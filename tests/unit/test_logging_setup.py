"""The logging setup: format, session id, levels, secrets, rotation, failure tolerance."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from typer.testing import CliRunner

import crapai.logging_setup as ls
from crapai.cli import app
from crapai.services.project import create_project

runner = CliRunner()


@pytest.fixture(autouse=True)
def clean_handlers() -> None:
    ls.detach_all()
    yield
    ls.detach_all()
    logging.getLogger("crapai").setLevel(logging.NOTSET)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    return create_project(tmp_path / "p", template="demo").root


def flush() -> None:
    for handler in logging.getLogger("crapai").handlers:
        handler.flush()


@pytest.mark.parametrize(
    "text,expected",
    [
        ("key sk-abcdefghijklmnop1234 end", "key *** end"),
        ("Authorization: Bearer abcdefghijkl.mnopqrstuvwx", "Authorization: Bearer ***"),
        ("OPENAI_API_KEY=abc123 next", "OPENAI_API_KEY=*** next"),
        ("password: hunter2", "password:***"),
        ("the token count was 12", "the token count was 12"),
        ("no secret here", "no secret here"),
        ("sk-short", "sk-short"),
    ],
)
def test_secrets_are_masked(text: str, expected: str) -> None:
    assert ls.redact(text) == expected


def test_the_filter_masks_formatted_messages_and_adds_the_session() -> None:
    record = logging.LogRecord(
        "crapai.x", logging.INFO, "f.py", 1, "key %s", ("sk-abcdefghijklmnop1234",), None
    )
    assert ls.RedactingFilter().filter(record) is True
    assert record.getMessage() == "key ***" and record.session == ls.SESSION_ID  # type: ignore[attr-defined]


def test_a_line_in_the_project_log_has_time_level_session_and_logger(project: Path) -> None:
    assert ls.attach_project_log(project) is None
    logging.getLogger("crapai.test").info("Import of %s: %d records", "a.ris", 3)
    flush()
    line = (project / ".crapai" / "app.log").read_text(encoding="utf-8").strip().splitlines()[-1]
    assert f"INFO [{ls.SESSION_ID}] crapai.test: Import of a.ris: 3 records" in line
    assert line[:4].isdigit()  # starts with the year of the timestamp


def test_secrets_never_reach_the_file(project: Path) -> None:
    ls.attach_project_log(project)
    logging.getLogger("crapai.test").warning("failed with api_key=sk-abcdefghijklmnop1234")
    flush()
    text = (project / ".crapai" / "app.log").read_text(encoding="utf-8")
    assert "sk-abcdefghijklmnop1234" not in text and "api_key=***" in text


def test_attaching_twice_keeps_one_handler_and_a_new_project_replaces_it(
    project: Path, tmp_path: Path
) -> None:
    ls.attach_project_log(project)
    ls.attach_project_log(project)
    handlers = [
        h for h in logging.getLogger("crapai").handlers if getattr(h, "crapai_tag", "") == "project"
    ]
    assert len(handlers) == 1
    other = create_project(tmp_path / "q", template="demo").root
    ls.attach_project_log(other)
    handlers = [
        h for h in logging.getLogger("crapai").handlers if getattr(h, "crapai_tag", "") == "project"
    ]
    assert len(handlers) == 1 and str(other.resolve()) in handlers[0].baseFilename  # type: ignore[attr-defined]


def test_a_folder_without_a_state_folder_is_ignored(tmp_path: Path) -> None:
    assert ls.attach_project_log(tmp_path) is None
    assert not [h for h in logging.getLogger("crapai").handlers if getattr(h, "crapai_tag", "")]


def test_an_unwritable_log_is_reported_not_raised(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*args: object, **kwargs: object) -> None:
        raise PermissionError("read-only share")

    monkeypatch.setattr(ls.logging.handlers, "RotatingFileHandler", refuse)
    assert "cannot write the log file (PermissionError)" in (ls.attach_project_log(project) or "")


@pytest.mark.parametrize(
    "explicit,env,verbose,expected",
    [
        (None, None, False, logging.INFO),
        ("debug", None, False, logging.DEBUG),
        (None, "WARNING", False, logging.WARNING),
        ("ERROR", "DEBUG", False, logging.ERROR),  # explicit beats the environment
        (None, "nonsense", False, logging.INFO),
        (None, "", False, logging.INFO),
        ("ERROR", None, True, logging.DEBUG),  # --verbose beats everything
        (logging.WARNING, None, False, logging.WARNING),
    ],
)
def test_level_resolution(
    monkeypatch: pytest.MonkeyPatch, explicit: object, env: str | None, verbose: bool, expected: int
) -> None:
    if env is None:
        monkeypatch.delenv(ls.LEVEL_ENV, raising=False)
    else:
        monkeypatch.setenv(ls.LEVEL_ENV, env)
    assert ls.resolve_level(explicit, verbose=verbose) == expected  # type: ignore[arg-type]


def test_the_environment_level_reaches_the_project_log(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(ls.LEVEL_ENV, "WARNING")
    ls.attach_project_log(project)
    logging.getLogger("crapai.test").info("hidden")
    logging.getLogger("crapai.test").warning("shown")
    flush()
    text = (project / ".crapai" / "app.log").read_text(encoding="utf-8")
    assert "shown" in text and "hidden" not in text


def test_the_log_rotates(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ls, "LOG_MAX_BYTES", 2000)
    ls.attach_project_log(project)
    for number in range(200):
        logging.getLogger("crapai.test").info("line %d %s", number, "x" * 50)
    flush()
    names = sorted(p.name for p in (project / ".crapai").glob("app.log*"))
    assert names[0] == "app.log" and len(names) == 1 + ls.LOG_BACKUPS


def test_read_log_tail(project: Path) -> None:
    ls.attach_project_log(project)
    for number in range(30):
        logging.getLogger("crapai.test").info("entry %d", number)
    flush()
    tail = ls.read_log_tail(project, 5)
    assert len(tail) == 5 and tail[-1].endswith("entry 29")
    assert ls.read_log_tail(project / "missing", 5) == []


def test_console_logging_prints_to_stderr(capsys: pytest.CaptureFixture[str]) -> None:
    ls.enable_console_log(logging.DEBUG)
    logging.getLogger("crapai.test").debug("visible detail")
    assert "visible detail" in capsys.readouterr().err


def test_the_verbose_option_shows_detail_and_fills_the_file(project: Path) -> None:
    result = runner.invoke(app, ["--verbose", "dedup", str(project), "--lang", "en"])
    assert result.exit_code == 0
    flush()
    log = (project / ".crapai" / "app.log").read_text(encoding="utf-8")
    assert "Dedup (" in log
    assert "DEBUG" in log or "INFO" in log
