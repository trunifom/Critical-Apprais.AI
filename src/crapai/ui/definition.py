"""The project definition as the interface edits it: description, research questions, criteria.

Everything the model is told about the review lives in a few places of ``project.yaml``:

``project.title`` / ``project.description``
    Name and short description (the *project description*).
``objectives``
    The research questions or aims, one per entry.
``criteria``
    The framework (PICOS, SPIDER, PECO, PIRD or CUSTOM) and, for each element of the framework,
    one inclusion text and one exclusion text.

This module turns those values into a plain :class:`Definition` for a form, checks it, and turns
it back into the dotted settings that go to the overrides file (``project.overrides.yaml``, which
wins over ``project.yaml`` and keeps its comments intact). It imports no Streamlit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from crapai.config.loader import resolve_config
from crapai.criteria.template import CriteriaTemplate
from crapai.project.workspace import Workspace

FRAMEWORKS: tuple[str, ...] = ("PICOS", "SPIDER", "PECO", "PIRD", "CUSTOM")


@dataclass
class Definition:
    """Description, research questions and criteria of one project.

    Attributes:
        title: Name of the review.
        description: Short description of the aim and scope.
        objectives: Research questions or aims, one per entry (empty entries are dropped).
        framework: One of :data:`FRAMEWORKS`.
        custom_fields: Element names of a ``CUSTOM`` framework.
        inclusion: Inclusion text per element.
        exclusion: Exclusion text per element.
    """

    title: str = ""
    description: str = ""
    objectives: list[str] = field(default_factory=list)
    framework: str = "PICOS"
    custom_fields: list[str] = field(default_factory=list)
    inclusion: dict[str, str] = field(default_factory=dict)
    exclusion: dict[str, str] = field(default_factory=dict)


def framework_elements(framework: str, custom_fields: list[str] | None = None) -> list[str]:
    """The element names of a framework, in their order (``CUSTOM``: the given names)."""
    names = [c.strip() for c in (custom_fields or []) if c.strip()]
    return CriteriaTemplate(framework, custom_fields=names, lang="en").get_fields()


def load_definition(folder: Any) -> Definition:
    """Read the definition in force (``project.yaml`` plus the overrides file).

    Raises:
        SaraError: if the configuration cannot be read.
    """
    config = resolve_config(Workspace(folder).project_yaml)
    criteria = config.criteria
    return Definition(
        title=config.project.title,
        description=config.project.description,
        objectives=list(config.objectives),
        framework=criteria.framework,
        custom_fields=list(criteria.custom_fields),
        inclusion=dict(criteria.inclusion),
        exclusion=dict(criteria.exclusion),
    )


def problems(definition: Definition) -> list[str]:
    """What is wrong with a definition, as text keys (empty list = fine).

    Keys: ``title`` (empty title), ``inclusion`` (no inclusion criterion filled in for the
    elements of the chosen framework), ``custom_fields`` (CUSTOM without element names).
    """
    found: list[str] = []
    if not definition.title.strip():
        found.append("title")
    if definition.framework == "CUSTOM" and not any(c.strip() for c in definition.custom_fields):
        found.append("custom_fields")
        return found
    elements = framework_elements(definition.framework, definition.custom_fields)
    if not any(definition.inclusion.get(name, "").strip() for name in elements):
        found.append("inclusion")
    return found


def to_settings(definition: Definition) -> dict[str, Any]:
    """The dotted settings that store a definition (for ``set_values``).

    Only the elements of the chosen framework are written, empty ones as empty text, so that a
    changed framework does not keep texts of the old one in force for the new elements.
    """
    custom = [c.strip() for c in definition.custom_fields if c.strip()]
    elements = framework_elements(definition.framework, custom)
    return {
        "project.title": definition.title.strip(),
        "project.description": definition.description.strip(),
        "objectives": [o.strip() for o in definition.objectives if o.strip()],
        "criteria.framework": definition.framework,
        "criteria.custom_fields": custom if definition.framework == "CUSTOM" else [],
        "criteria.inclusion": {n: definition.inclusion.get(n, "").strip() for n in elements},
        "criteria.exclusion": {n: definition.exclusion.get(n, "").strip() for n in elements},
    }
