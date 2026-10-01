"""The Streamlit interface, run for real with ``AppTest`` (skipped without Streamlit)."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from crapai.services.importing import ImportRequest, import_source  # noqa: E402
from crapai.services.project import create_project  # noqa: E402
from crapai.ui.context import PROJECT_ENV  # noqa: E402

APP = Path(__file__).resolve().parents[2] / "src" / "crapai" / "ui" / "streamlit_app.py"
ABSTRACT = "The trial enrolled adults and measured outcomes over twelve months. " * 5
RIS = (
    "TY  - JOUR\nTI  - Effects of exercise on mood in adults\nDO  - 10.1000/a\nPY  - 2020\n"
    f"AB  - {ABSTRACT}\nER  - \n"
    "TY  - JOUR\nTI  - Effects of exercise on mood in adults\nDO  - 10.1000/a\nPY  - 2020\nER  - \n"
)


def texts(elements: object) -> str:
    return " | ".join(str(getattr(e, "value", "")) for e in elements)  # type: ignore[attr-defined]


def page_text(at: AppTest) -> str:
    """All visible text of the main area (headers, messages, captions, markdown)."""
    parts: list[str] = []
    for group in (
        at.header,
        at.subheader,
        at.success,
        at.warning,
        at.error,
        at.info,
        at.caption,
        at.markdown,
    ):
        parts.append(texts(group))
    return " | ".join(parts)


def fresh(monkeypatch: pytest.MonkeyPatch, folder: Path | None = None) -> AppTest:
    if folder is None:
        monkeypatch.delenv(PROJECT_ENV, raising=False)
    else:
        monkeypatch.setenv(PROJECT_ENV, str(folder))
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    monkeypatch.delenv("LC_ALL", raising=False)
    return AppTest.from_file(str(APP), default_timeout=60)


def goto(at: AppTest, page: str) -> AppTest:
    at.sidebar.button(key=f"nav_{page}").click()
    return at.run()


@pytest.fixture
def empty_project(tmp_path: Path) -> Path:
    return create_project(tmp_path / "p", template="demo").root


@pytest.fixture
def filled_project(tmp_path: Path) -> Path:
    workspace = create_project(tmp_path / "f", template="demo")
    source = tmp_path / "s.ris"
    source.write_text(RIS, encoding="utf-8")
    import_source(workspace, ImportRequest(source, label="S"))
    return workspace.root


def test_the_start_page_renders_without_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    at = fresh(monkeypatch).run()
    assert not at.exception
    assert "Open or create a project" in page_text(at)
    assert "Results are proposals" in page_text(at)
    assert at.session_state["page"] == "start"
    assert "No project open" in page_text(at)


def test_pages_that_need_a_project_explain_why_they_are_locked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    at = fresh(monkeypatch).run()
    for page in ("project", "data", "check", "flow", "export"):
        goto(at, page)
        assert not at.exception
        assert "Open or create a project first" in page_text(at), page


def test_a_project_named_on_the_command_line_opens_on_the_project_page(
    monkeypatch: pytest.MonkeyPatch, empty_project: Path
) -> None:
    at = fresh(monkeypatch, empty_project).run()
    assert not at.exception
    assert at.session_state["page"] == "project"
    assert "Demo review" in page_text(at)
    assert at.text_area(key="yaml_text").value.startswith("#")


def test_creating_a_project_in_the_interface(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    at = fresh(monkeypatch).run()
    target = tmp_path / "made"
    at.text_input(key="create_folder_text").set_value(str(target))
    at.text_input(key="create_title").set_value("My own review")
    at.run()
    at.button(key="create_button").click()
    at.run()
    assert not at.exception
    assert (target / "project.yaml").exists()
    assert at.session_state["page"] == "project"
    assert "My own review" in page_text(at) + texts(at.metric)


def test_opening_a_folder_that_is_no_project_shows_an_error_not_a_crash(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    at = fresh(monkeypatch).run()
    at.text_input(key="open_folder_text").set_value(str(tmp_path / "nothing"))
    at.run()
    at.button(key="open_button").click()
    at.run()
    assert not at.exception
    assert "E404" in page_text(at)


def test_the_data_page_shows_the_records_and_filters_them(
    monkeypatch: pytest.MonkeyPatch, filled_project: Path
) -> None:
    at = fresh(monkeypatch, filled_project).run()
    goto(at, "data")
    assert not at.exception
    assert len(at.dataframe) == 1
    at.selectbox(key="records_filter").set_value("__none__")
    at.run()
    assert not at.exception


def test_the_check_runs_and_shows_duplicates_and_the_estimate(
    monkeypatch: pytest.MonkeyPatch, filled_project: Path
) -> None:
    at = fresh(monkeypatch, filled_project).run()
    goto(at, "check")
    assert "Press the button" in page_text(at)
    at.button(key="run_check").click()
    at.run()
    assert not at.exception
    text = page_text(at)
    assert any("DUPLICATE" in table.value.to_string() for table in at.table)
    assert "Tokens, cost and duration" in text
    assert len(at.metric) >= 6
    assert (filled_project / "data" / "events.jsonl").exists()


def test_the_check_of_an_empty_project_is_locked_until_records_exist(
    monkeypatch: pytest.MonkeyPatch, empty_project: Path
) -> None:
    at = fresh(monkeypatch, empty_project).run()
    goto(at, "check")
    assert "Import records first" in page_text(at)


def test_the_flow_page_shows_the_numbers_and_warns_when_the_check_is_old(
    monkeypatch: pytest.MonkeyPatch, filled_project: Path
) -> None:
    at = fresh(monkeypatch, filled_project).run()
    goto(at, "flow")
    assert not at.exception
    values = [m.value for m in at.metric]
    assert "2" in values  # two records identified
    goto(at, "check")
    at.button(key="run_check").click()
    at.run()
    goto(at, "flow")
    assert not at.exception
    assert not at.warning or "STALE" not in texts(at.warning)


def test_the_export_page_writes_a_file(
    monkeypatch: pytest.MonkeyPatch, filled_project: Path
) -> None:
    at = fresh(monkeypatch, filled_project).run()
    goto(at, "export")
    at.button(key="export_button").click()
    at.run()
    assert not at.exception
    assert "Exported 2 record(s)" in page_text(at)
    assert len(list((filled_project / "exports").glob("records-all-*.csv"))) == 1


def test_the_export_page_can_write_the_flow_and_a_ris_file(
    monkeypatch: pytest.MonkeyPatch, filled_project: Path
) -> None:
    at = fresh(monkeypatch, filled_project).run()
    goto(at, "export")
    at.radio(key="export_what").set_value("flow")
    at.run()
    at.button(key="export_button").click()
    at.run()
    assert (filled_project / "exports" / "prisma_flow.json").exists()
    at.radio(key="export_what").set_value("records")
    at.run()
    at.selectbox(key="export_format_records").set_value("ris")
    at.run()
    at.button(key="export_button").click()
    at.run()
    assert not at.exception
    assert list((filled_project / "exports").glob("records-all-*.ris"))


def test_the_run_page_is_locked_until_records_exist(
    monkeypatch: pytest.MonkeyPatch, empty_project: Path
) -> None:
    at = fresh(monkeypatch, empty_project).run()
    goto(at, "run")
    assert not at.exception
    assert "Import records first" in page_text(at)


def test_the_project_yaml_is_checked_before_it_is_saved(
    monkeypatch: pytest.MonkeyPatch, empty_project: Path
) -> None:
    at = fresh(monkeypatch, empty_project).run()
    before = (empty_project / "project.yaml").read_bytes()
    at.text_area(key="yaml_text").set_value("project: [broken")
    at.run()
    at.button(key="save_yaml").click()
    at.run()
    assert not at.exception
    assert "E203" in page_text(at) and (empty_project / "project.yaml").read_bytes() == before
    text = before.decode("utf-8").replace("Demo review", "Edited review")
    at.text_area(key="yaml_text").set_value(text)
    at.run()
    at.button(key="save_yaml").click()
    at.run()
    assert "project.yaml saved" in page_text(at)
    assert b"Edited review" in (empty_project / "project.yaml").read_bytes()


def test_the_language_can_be_switched(monkeypatch: pytest.MonkeyPatch, empty_project: Path) -> None:
    at = fresh(monkeypatch, empty_project).run()
    at.sidebar.selectbox(key="lang").set_value("de")
    at.run()
    assert not at.exception
    assert "Daten prüfen" in " ".join(b.label for b in at.sidebar.button)
    goto(at, "check")
    assert "Importieren Sie zuerst" in page_text(at)


def test_the_help_page_lists_the_error_codes_and_the_log(
    monkeypatch: pytest.MonkeyPatch, filled_project: Path
) -> None:
    at = fresh(monkeypatch, filled_project).run()
    goto(at, "help")
    assert not at.exception
    table = at.dataframe[0].value
    assert "E404" in set(table["Code"]) and "E999" in set(table["Code"])


def test_the_settings_page_shows_paths_and_the_price_list(
    monkeypatch: pytest.MonkeyPatch, filled_project: Path
) -> None:
    at = fresh(monkeypatch, filled_project).run()
    goto(at, "settings")
    assert not at.exception and "No pricing.csv" in page_text(at)
    (filled_project / "pricing.csv").write_text(
        "provider,model,price_input_per_1k,price_output_per_1k\nopenai,gpt-4o-mini,0.1,0.2\n",
        encoding="utf-8",
    )
    at.run()
    assert not at.exception and len(at.dataframe) == 2  # sources of the values, price list


def test_closing_the_project_returns_to_the_start_page(
    monkeypatch: pytest.MonkeyPatch, empty_project: Path
) -> None:
    at = fresh(monkeypatch, empty_project).run()
    at.sidebar.button(key="close_project").click()
    at.run()
    assert not at.exception
    assert at.session_state["page"] == "start" and "No project open" in page_text(at)


def test_a_project_that_disappears_is_reported_and_the_start_page_returns(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    folder = create_project(tmp_path / "gone", template="demo").root
    at = fresh(monkeypatch, folder).run()
    (folder / "project.yaml").unlink()
    (folder / ".crapai" / "version").unlink()
    at.run()
    assert not at.exception


def test_the_settings_form_saves_a_change_and_can_reset_it(
    monkeypatch: pytest.MonkeyPatch, empty_project: Path
) -> None:
    at = fresh(monkeypatch, empty_project).run()
    goto(at, "settings")
    assert not at.exception
    field = at.number_input(key="set::quality.short_abstract_words::0")
    assert field.value == 40
    field.set_value(25)
    at.run()
    at.button[0].click()  # the submit button of the form
    at.run()
    assert not at.exception
    overrides = (empty_project / "project.overrides.yaml").read_text(encoding="utf-8")
    assert "short_abstract_words: 25" in overrides
    at.button(key="reset_settings").click()
    at.run()
    assert not at.exception and not (empty_project / "project.overrides.yaml").exists()


# --- the run page -----------------------------------------------------------------------------------


def make_run(
    folder: Path,
    state: str,
    *,
    done: int = 4,
    total: int = 10,
    ok: int = 4,
    last_error: dict[str, str] | None = None,
    stop_reason: str = "",
) -> None:
    """Write a manifest as a worker process would have left it."""
    from crapai.screening.store import Manifest, RunStore

    store = RunStore(folder / "runs" / "2026-10-01T10-00_run-001")
    manifest = Manifest(run_id=store.folder.name, state=state, stop_reason=stop_reason)
    manifest.counts = {"total": total, "done": done, "ok": ok}
    manifest.usage = {"cost": 0.25, "currency": "USD"}
    manifest.run_settings = {"batch_size": 5}
    manifest.batches = [
        {"index": 0, "size": 5, "done": 4, "ok": ok, "errors": done - ok, "status": "verified"}
    ]
    manifest.last_error = last_error or {}
    store.create(manifest)


def use_mock_provider(folder: Path) -> None:
    import yaml

    path = folder / "project.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["llm"].update({"provider": "mock", "model": "S1", "base_url": None})
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def test_the_run_page_offers_a_start_that_needs_the_consent(
    monkeypatch: pytest.MonkeyPatch, filled_project: Path
) -> None:
    use_mock_provider(filled_project)
    at = fresh(monkeypatch, filled_project).run()
    goto(at, "run")
    assert not at.exception
    text = page_text(at)
    assert "Screening run" in text and "No run yet" in text
    assert at.button(key="run_start").disabled
    at.checkbox(key="run_confirm").check()
    at.run()
    assert not at.button(key="run_start").disabled


def test_starting_from_the_page_spawns_one_process_and_says_so(
    monkeypatch: pytest.MonkeyPatch, filled_project: Path
) -> None:
    from crapai.ui import actions

    use_mock_provider(filled_project)
    started: list[list[str]] = []

    class FakePopen:
        def __init__(self, command: list[str], **kwargs: object) -> None:
            started.append(command)
            self.pid = 1

    monkeypatch.setattr(actions.subprocess, "Popen", FakePopen)
    at = fresh(monkeypatch, filled_project).run()
    goto(at, "run")
    at.number_input(key="run_sample").set_value(3)
    at.checkbox(key="run_confirm").check()
    at.run()
    at.button(key="run_start").click()
    at.run()
    assert not at.exception
    assert len(started) == 1 and "--sample" in started[0] and "3" in started[0]
    assert "Starting the run" in page_text(at)


def test_a_start_that_cannot_work_shows_the_error_and_starts_nothing(
    monkeypatch: pytest.MonkeyPatch, filled_project: Path
) -> None:
    import yaml

    from crapai.ui import actions

    path = filled_project / "project.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["llm"].update(
        {
            "provider": "openai",
            "model": "gpt-4o-mini",
            "base_url": None,
            "api_key_env": "NO_SUCH_VAR_Z",
        }
    )
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    monkeypatch.delenv("NO_SUCH_VAR_Z", raising=False)
    started: list[object] = []
    monkeypatch.setattr(actions.subprocess, "Popen", lambda *a, **k: started.append(a))
    at = fresh(monkeypatch, filled_project).run()
    goto(at, "run")
    at.checkbox(key="run_confirm").check()
    at.run()
    at.button(key="run_start").click()
    at.run()
    assert not at.exception and not started
    assert "E301" in page_text(at) and "NO_SUCH_VAR_Z" in page_text(at)


def test_a_working_run_shows_its_progress_and_the_pause_button(
    monkeypatch: pytest.MonkeyPatch, filled_project: Path
) -> None:
    use_mock_provider(filled_project)
    make_run(filled_project, "running", done=4, total=10, ok=4)
    at = fresh(monkeypatch, filled_project).run()
    goto(at, "run")
    assert not at.exception
    assert "is working" in page_text(at)
    assert at.get("progress")
    at.button(key="run_pause").click()
    at.run()
    store_control = filled_project / "runs" / "2026-10-01T10-00_run-001" / "control.json"
    assert store_control.exists() and "pause" in store_control.read_text(encoding="utf-8")


def test_a_paused_run_explains_why_and_offers_to_resume(
    monkeypatch: pytest.MonkeyPatch, filled_project: Path
) -> None:
    use_mock_provider(filled_project)
    make_run(
        filled_project, "paused", done=4, total=10, ok=4,
        last_error={"code": "E307", "message": "The credit is used up"},
        stop_reason="the credit or quota is used up",
    )  # fmt: skip
    at = fresh(monkeypatch, filled_project).run()
    goto(at, "run")
    assert not at.exception
    text = page_text(at)
    assert "PAUSED" in text and "E307" in text and "Resume" in text
    assert "run_sample" not in [w.key for w in at.number_input]  # a resume has no sample box


def test_a_finished_run_with_errors_lists_the_failed_records(
    monkeypatch: pytest.MonkeyPatch, filled_project: Path
) -> None:
    use_mock_provider(filled_project)
    make_run(filled_project, "completed", done=10, total=10, ok=8)
    at = fresh(monkeypatch, filled_project).run()
    goto(at, "run")
    assert not at.exception
    assert "completed" in page_text(at) and "2 with errors" in page_text(at)


def test_a_run_that_stopped_saving_is_reported_as_stalled_not_working(
    monkeypatch: pytest.MonkeyPatch, filled_project: Path
) -> None:
    import re

    use_mock_provider(filled_project)
    make_run(filled_project, "running")
    manifest = filled_project / "runs" / "2026-10-01T10-00_run-001" / "manifest.json"
    manifest.write_text(
        re.sub(
            r'"updated_at": "[^"]*"',
            '"updated_at": "2020-01-01T00:00:00+00:00"',
            manifest.read_text(encoding="utf-8"),
        ),
        encoding="utf-8",
    )
    at = fresh(monkeypatch, filled_project).run()
    goto(at, "run")
    assert not at.exception
    assert "has not saved anything" in page_text(at) and "_run-001 is working" not in page_text(at)


# --- menu, language, design, text size and help ---------------------------------------------------------


def css_of(at: AppTest) -> str:
    """The style sheet the page inserted."""
    return " ".join(str(getattr(m, "value", "")) for m in at.markdown if "<style>" in str(m.value))


def test_the_menu_is_made_of_buttons_with_clear_names_and_no_streamlit_page_names(
    monkeypatch: pytest.MonkeyPatch, filled_project: Path
) -> None:
    at = fresh(monkeypatch, filled_project).run()
    assert not at.exception
    assert not at.sidebar.radio  # no plain-text menu any more
    keys = {b.key for b in at.sidebar.button}
    assert {
        f"nav_{page}"
        for page in (
            "start",
            "project",
            "data",
            "check",
            "run",
            "flow",
            "export",
            "settings",
            "help",
        )
    } <= keys
    labels = " | ".join(b.label for b in at.sidebar.button)
    assert "Import data" in labels and "Run screening" in labels and "Export results" in labels
    for technical in ("streamlit app", "common"):
        assert technical not in labels.lower()


def test_the_title_comes_first_in_the_sidebar(
    monkeypatch: pytest.MonkeyPatch, filled_project: Path
) -> None:
    at = fresh(monkeypatch, filled_project).run()
    first = str(at.sidebar.markdown[0].value)
    assert "Critical Apprais.AI" in first and "crapai-brand" in first


def test_the_language_stays_when_the_page_changes_and_after_a_restart(
    monkeypatch: pytest.MonkeyPatch, filled_project: Path
) -> None:
    at = fresh(monkeypatch, filled_project).run()
    at.sidebar.selectbox(key="lang").set_value("de")
    at.run()
    for page in ("check", "data", "settings", "run"):
        goto(at, page)
        assert at.session_state["lang"] == "de", page
        assert at.sidebar.selectbox(key="lang").value == "de"
    assert "Daten prüfen" in " ".join(b.label for b in at.sidebar.button)
    again = fresh(monkeypatch, filled_project).run()  # a new session: the choice was remembered
    assert again.session_state["lang"] == "de"
    assert "Daten importieren" in " ".join(b.label for b in again.sidebar.button)


def test_light_and_dark_can_be_switched_and_are_remembered(
    monkeypatch: pytest.MonkeyPatch, filled_project: Path
) -> None:
    at = fresh(monkeypatch, filled_project).run()
    assert at.session_state["theme"] == "light" and "#FFFFFF" in css_of(at)
    at.sidebar.button(key="theme_toggle").click()
    at.run()
    assert at.session_state["theme"] == "dark" and "#0F141B" in css_of(at)
    goto(at, "check")
    assert at.session_state["theme"] == "dark"  # the page change keeps it
    assert fresh(monkeypatch, filled_project).run().session_state["theme"] == "dark"
    at.sidebar.button(key="theme_toggle").click()
    at.run()
    assert at.session_state["theme"] == "light"


def test_the_text_size_can_be_switched_and_is_remembered(
    monkeypatch: pytest.MonkeyPatch, filled_project: Path
) -> None:
    at = fresh(monkeypatch, filled_project).run()
    assert "font-size: 16px" in css_of(at)
    at.sidebar.button(key="size_toggle").click()
    at.run()
    assert at.session_state["size"] == "large" and "font-size: 19px" in css_of(at)
    assert fresh(monkeypatch, filled_project).run().session_state["size"] == "large"


def test_a_damaged_choice_file_does_not_break_the_start(
    monkeypatch: pytest.MonkeyPatch, filled_project: Path
) -> None:
    from crapai.ui.theme import UiPrefs

    prefs = UiPrefs()
    prefs.path.parent.mkdir(parents=True, exist_ok=True)
    prefs.path.write_text('{"theme": "neon"', encoding="utf-8")
    at = fresh(monkeypatch, filled_project).run()
    assert not at.exception and at.session_state["theme"] == "light"


@pytest.mark.parametrize("lang", ["en", "de"])
def test_every_control_of_every_page_has_a_help_text(
    monkeypatch: pytest.MonkeyPatch, filled_project: Path, lang: str
) -> None:
    use_mock_provider(filled_project)
    at = fresh(monkeypatch, filled_project).run()
    at.sidebar.selectbox(key="lang").set_value(lang)
    at.run()
    for page in (
        "start",
        "overview",
        "project",
        "data",
        "check",
        "run",
        "flow",
        "export",
        "results",
        "settings",
        "help",
    ):
        goto(at, page)
        assert not at.exception, page
        assert at.session_state["missing_help"] == set(), (page, at.session_state["missing_help"])


def test_notices_are_drawn_as_own_boxes(
    monkeypatch: pytest.MonkeyPatch, empty_project: Path
) -> None:
    at = fresh(monkeypatch, empty_project).run()
    at.text_area(key="yaml_text").set_value("project: [broken")
    at.run()
    at.button(key="save_yaml").click()
    at.run()
    boxes = [str(m.value) for m in at.markdown if "crapai-notice" in str(m.value)]
    assert any("crapai-error" in b and "E203" in b for b in boxes)


# --- introductions, overview, definition, results ------------------------------------------------------

ALL_PAGES = (
    "start", "overview", "project", "data", "check", "run", "flow", "export", "results",
    "settings", "help",
)  # fmt: skip


@pytest.fixture
def run_project(tmp_path: Path) -> Path:
    """A project with a finished mock run (24 records)."""
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "unit"))
    from results_helpers import project_with_run

    return project_with_run(tmp_path).root


@pytest.mark.parametrize("lang", ["en", "de"])
def test_every_page_starts_with_the_four_part_introduction(
    monkeypatch: pytest.MonkeyPatch, run_project: Path, lang: str
) -> None:
    at = fresh(monkeypatch, run_project).run()
    at.sidebar.selectbox(key="lang").set_value(lang)
    at.run()
    for page in ALL_PAGES:
        goto(at, page)
        assert not at.exception, page
        html = " ".join(str(m.value) for m in at.markdown)
        assert html.count('class="crapai-intro-label"') == 4, page
        assert at.session_state["missing_help"] == set(), (page, at.session_state["missing_help"])


def test_the_overview_shows_progress_and_jumps_to_a_step(
    monkeypatch: pytest.MonkeyPatch, run_project: Path
) -> None:
    at = fresh(monkeypatch, run_project).run()
    goto(at, "overview")
    text = page_text(at)
    assert at.get("progress") and "Next:" in text
    at.button(key="overview_open_export").click()
    at.run()
    assert at.session_state["page"] == "export"


def test_the_overview_points_to_the_next_open_step(
    monkeypatch: pytest.MonkeyPatch, filled_project: Path
) -> None:
    at = fresh(monkeypatch, filled_project).run()
    goto(at, "overview")
    assert not at.exception
    assert "Next:" in page_text(at)
    next_buttons = [b for b in at.button if b.key and b.key.startswith("overview_open_next_")]
    assert len(next_buttons) == 1
    next_buttons[0].click()
    at.run()
    assert at.session_state["page"] in ("project", "check", "run")


def test_description_questions_and_criteria_are_entered_and_saved_on_the_project_page(
    monkeypatch: pytest.MonkeyPatch, empty_project: Path
) -> None:
    at = fresh(monkeypatch, empty_project).run()
    assert not at.exception
    at.text_input(key="def_title").set_value("Exercise and mood")
    at.text_area(key="def_description").set_value("Adults, randomised trials.")
    at.text_area(key="def_objectives").set_value("Does exercise help?\nHow much?")
    at.selectbox(key="def_framework").set_value("PECO")
    at.run()
    at.text_area(key="criteria_in_PECO_Population").set_value("adults with depression")
    at.text_area(key="criteria_out_PECO_Population").set_value("children")
    at.run()
    at.button(key="save_definition").click()
    at.run()
    assert not at.exception
    assert "Saved." in page_text(at)
    from crapai.config.loader import resolve_config

    config = resolve_config(empty_project / "project.yaml")
    assert config.project.title == "Exercise and mood" and config.criteria.framework == "PECO"
    assert config.objectives == ["Does exercise help?", "How much?"]
    assert config.criteria.inclusion["Population"] == "adults with depression"
    assert config.criteria.exclusion["Population"] == "children"


def test_a_definition_without_inclusion_criteria_is_refused_with_a_reason(
    monkeypatch: pytest.MonkeyPatch, empty_project: Path
) -> None:
    at = fresh(monkeypatch, empty_project).run()
    for name in ("Population", "Intervention", "Comparison", "Outcome", "Study Design"):
        at.text_area(key=f"criteria_in_PICOS_{name}").set_value("")
    at.run()
    at.button(key="save_definition").click()
    at.run()
    assert "at least one element" in page_text(at) or "mindestens einem Element" in page_text(at)
    assert not (empty_project / "project.overrides.yaml").exists()


def test_the_project_file_editor_is_folded_away_by_default(
    monkeypatch: pytest.MonkeyPatch, empty_project: Path
) -> None:
    at = fresh(monkeypatch, empty_project).run()
    labels = {e.label: e.proto.expanded for e in at.expander}
    assert any(label.startswith("Edit") or "project.yaml" in label for label in labels)
    editor = next(e for e in at.expander if "project.yaml" in e.label)
    assert editor.proto.expanded is False


def test_the_results_page_draws_charts_for_the_run_of_the_project(
    monkeypatch: pytest.MonkeyPatch, run_project: Path
) -> None:
    at = fresh(monkeypatch, run_project).run()
    goto(at, "results")
    assert not at.exception
    assert len(at.get("vega_lite_chart")) >= 3
    labels = " | ".join(e.label for e in at.expander)
    assert "Decisions at a glance" in labels and "By source" in labels
    at.checkbox(key="results_normalise").check()
    at.run()
    assert not at.exception


def test_the_results_page_compares_two_runs(
    monkeypatch: pytest.MonkeyPatch, run_project: Path
) -> None:
    from crapai.llm.mock_provider import MockProvider
    from crapai.project.workspace import Workspace
    from crapai.services import screening as svc

    svc.screen_project(
        Workspace(run_project),
        svc.RunOptions(provider=MockProvider("S12"), install_signal_handler=False),
    )
    at = fresh(monkeypatch, run_project).run()
    goto(at, "results")
    assert not at.exception
    expander = next(e for e in at.expander if "Compare runs" in e.label)
    assert expander.proto.expanded is False
    at.multiselect(key="results_compare_runs").set_value(
        at.multiselect(key="results_compare_runs").options[:2]
    )
    at.run()
    assert not at.exception
    assert at.session_state["missing_help"] == set()
    assert any("Fleiss" in m.label for m in at.metric)


def test_the_results_page_reads_an_uploaded_export_and_refuses_other_files(
    monkeypatch: pytest.MonkeyPatch, run_project: Path
) -> None:
    from crapai.project.workspace import Workspace
    from crapai.services.results import export_results

    exported = export_results(Workspace(run_project), "csv").path
    at = fresh(monkeypatch, None).run()  # no project open: only the file route
    goto(at, "results")
    assert not at.exception and "Choose a results file" in page_text(at)
    from crapai.stats.results import read_table_file

    rows = read_table_file(exported.name, exported.read_bytes())
    assert len(rows) == 24


def test_the_export_page_lists_the_files_and_offers_the_results(
    monkeypatch: pytest.MonkeyPatch, run_project: Path
) -> None:
    at = fresh(monkeypatch, run_project).run()
    goto(at, "export")
    at.radio(key="export_what").set_value("results")
    at.run()
    at.button(key="export_button").click()
    at.run()
    assert not at.exception
    assert list((run_project / "exports").glob("results-*.csv"))
    at.run()
    assert any(
        b.key and b.key.startswith("download_file_") for b in at.get("download_button")
    ) or at.get("download_button")


def test_the_data_page_lists_what_was_imported(
    monkeypatch: pytest.MonkeyPatch, run_project: Path
) -> None:
    at = fresh(monkeypatch, run_project).run()
    goto(at, "data")
    assert not at.exception
    assert "Step 1" in page_text(at) and "Files already imported" in " ".join(
        e.label for e in at.expander
    )


def test_sidebar_buttons_are_left_aligned_in_the_style_sheet(
    monkeypatch: pytest.MonkeyPatch, filled_project: Path
) -> None:
    at = fresh(monkeypatch, filled_project).run()
    assert "justify-content: flex-start" in css_of(at) and "text-align: left" in css_of(at)
