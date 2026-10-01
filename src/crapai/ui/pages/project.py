"""Project page: describe the review, state the research questions, define the criteria.

The page answers "where do I enter what?" in three clearly separated blocks:

1. **Description** of the project (name, short description) and the **research questions**.
2. **Framework and criteria**: PICOS, SPIDER, PECO, PIRD or your own elements, and for every
   element what is included and what is excluded.
3. The **project file** itself (``project.yaml``) for people who want to edit it directly, folded
   away by default.

The first two blocks are saved into ``project.overrides.yaml`` (so ``project.yaml`` and its
comments stay as they are); the page says so.
"""

from __future__ import annotations

from typing import Any

from crapai.ui import actions
from crapai.ui.context import Context
from crapai.ui.definition import FRAMEWORKS, Definition, framework_elements, problems
from crapai.ui.pages.common import intro, metric_row, show_error
from crapai.ui.viewmodels import percent


def _state(st: Any, ctx: Context) -> None:
    overview, folder = ctx.overview, ctx.folder
    assert overview is not None and folder is not None
    st.caption(str(folder))
    if overview.config_ok:
        st.success(ctx.messages.text("cli.status.config_ok"))
    else:
        first = next(iter((overview.config_problem or "").splitlines()), "")
        st.warning(ctx.messages.text("cli.status.config_problem", problem=first))
    if overview.in_use:
        st.warning(ctx.messages.text("cli.status.in_use"))
    metric_row(
        st,
        [
            (ctx.t("bar.records"), overview.records),
            (ctx.t("bar.abstracts"), percent(overview.with_abstract, overview.records)),
            (ctx.t("bar.duplicates"), overview.duplicates),
            (ctx.t("project.imports"), overview.imports),
        ],
    )
    if overview.sources:
        with st.expander(ctx.t("project.sources"), expanded=False):
            st.table(
                {
                    ctx.t("project.source"): list(overview.sources),
                    ctx.t("bar.records"): list(overview.sources.values()),
                }
            )


def _description(st: Any, ctx: Context, current: Definition) -> tuple[str, str, list[str]]:
    st.markdown(f"##### {ctx.t('project.describe')}")
    st.caption(ctx.t("project.describe_hint"))
    title = st.text_input(ctx.t("project.name"), value=current.title, key="def_title")
    description = st.text_area(
        ctx.t("project.description"), value=current.description, height=110, key="def_description"
    )
    st.markdown(f"##### {ctx.t('project.questions')}")
    st.caption(ctx.t("project.questions_hint"))
    text = st.text_area(
        ctx.t("project.questions_label"),
        value="\n".join(current.objectives),
        height=110,
        key="def_objectives",
    )
    return title, description, [line.strip() for line in text.splitlines() if line.strip()]


def _criteria(
    st: Any, ctx: Context, current: Definition
) -> tuple[str, list[str], dict[str, str], dict[str, str]]:
    st.markdown(f"##### {ctx.t('project.framework_title')}")
    st.caption(ctx.t("project.framework_hint"))
    framework = st.selectbox(
        ctx.t("project.framework"),
        FRAMEWORKS,
        index=FRAMEWORKS.index(current.framework) if current.framework in FRAMEWORKS else 0,
        format_func=lambda name: ctx.t(f"framework.{name}"),
        key="def_framework",
    )
    custom: list[str] = []
    if framework == "CUSTOM":
        names = st.text_input(
            ctx.t("project.custom"), value=", ".join(current.custom_fields), key="def_custom"
        )
        custom = [n.strip() for n in names.split(",") if n.strip()]
    elements = framework_elements(framework, custom)
    inclusion: dict[str, str] = {}
    exclusion: dict[str, str] = {}
    if not elements:
        st.info(ctx.t("project.no_elements"))
    for name in elements:
        st.markdown(f"**{name}**")
        left, right = st.columns(2)
        inclusion[name] = left.text_area(
            ctx.t("project.include"),
            value=current.inclusion.get(name, ""),
            height=90,
            key=f"criteria_in_{framework}_{name}",
        )
        exclusion[name] = right.text_area(
            ctx.t("project.exclude"),
            value=current.exclusion.get(name, ""),
            height=90,
            key=f"criteria_out_{framework}_{name}",
        )
    return framework, custom, inclusion, exclusion


def _definition(st: Any, ctx: Context) -> None:
    folder = ctx.folder
    assert folder is not None
    loaded = actions.load_definition(ctx.messages, folder)
    if loaded.error is not None:
        show_error(st, ctx, loaded.error)
        return
    current = loaded.value
    assert current is not None
    st.info(ctx.t("project.saved_where"))
    title, description, objectives = _description(st, ctx, current)
    framework, custom, inclusion, exclusion = _criteria(st, ctx, current)
    new = Definition(title, description, objectives, framework, custom, inclusion, exclusion)
    if st.button(ctx.t("project.save_definition"), key="save_definition", type="primary"):
        found = problems(new)
        if found:
            for key in found:
                st.error(ctx.t(f"project.problem_{key}"))
            return
        outcome = actions.save_definition(ctx.messages, folder, new)
        if outcome.error is not None:
            show_error(st, ctx, outcome.error)
        else:
            st.session_state.pop("overview_token", None)
            st.success(ctx.t("project.definition_saved"))


def _yaml_editor(st: Any, ctx: Context) -> None:
    folder = ctx.folder
    assert folder is not None
    st.caption(ctx.t("project.edit_hint"))
    text = st.text_area(
        "project.yaml",
        actions.read_project_yaml(folder),
        height=420,
        key="yaml_text",
        label_visibility="collapsed",
    )
    if st.button(ctx.t("project.save"), key="save_yaml"):
        outcome = actions.save_project_yaml(ctx.messages, folder, text)
        if outcome.error is not None:
            show_error(st, ctx, outcome.error)
        else:
            st.session_state.pop("overview_token", None)
            st.success(ctx.t("project.saved"))


def render(st: Any, ctx: Context) -> None:
    """Draw the project page: state, description and questions, criteria, project file."""
    overview, folder = ctx.overview, ctx.folder
    if overview is None or folder is None:
        return
    st.header(ctx.t("project.title"))
    intro(st, ctx, "project")
    with st.expander(ctx.t("project.state"), expanded=False):
        _state(st, ctx)
    with st.expander(ctx.t("project.definition"), expanded=True):
        _definition(st, ctx)
    with st.expander(ctx.t("project.edit"), expanded=False):
        _yaml_editor(st, ctx)
