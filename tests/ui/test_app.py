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
ABSTRACT = "The trial enrolled adults and measured outcomes over twelve months. " * 3
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
    at.sidebar.radio(key="page").set_value(page)
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
    assert at.sidebar.radio(key="page").value == "start"
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
    assert at.sidebar.radio(key="page").value == "project"
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
    assert at.sidebar.radio(key="page").value == "project"
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
    at.selectbox(key="export_format").set_value("ris")
    at.run()
    at.button(key="export_button").click()
    at.run()
    assert not at.exception
    assert list((filled_project / "exports").glob("records-all-*.ris"))


def test_the_run_page_is_honest_that_screening_is_not_available(
    monkeypatch: pytest.MonkeyPatch, empty_project: Path
) -> None:
    at = fresh(monkeypatch, empty_project).run()
    goto(at, "run")
    assert not at.exception
    assert "Not available in this version" in page_text(at)


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
    assert any("Prüfen" in option for option in at.sidebar.radio(key="page").options)
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
    assert not at.exception and len(at.dataframe) == 1


def test_closing_the_project_returns_to_the_start_page(
    monkeypatch: pytest.MonkeyPatch, empty_project: Path
) -> None:
    at = fresh(monkeypatch, empty_project).run()
    at.sidebar.button(key="close_project").click()
    at.run()
    assert not at.exception
    assert at.sidebar.radio(key="page").value == "start" and "No project open" in page_text(at)


def test_a_project_that_disappears_is_reported_and_the_start_page_returns(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    folder = create_project(tmp_path / "gone", template="demo").root
    at = fresh(monkeypatch, folder).run()
    (folder / "project.yaml").unlink()
    (folder / ".crapai" / "version").unlink()
    at.run()
    assert not at.exception
