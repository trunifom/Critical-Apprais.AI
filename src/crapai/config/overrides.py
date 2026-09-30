"""Settings changed outside ``project.yaml``: the overrides file, and where every value comes from.

``project.yaml`` is written and commented by hand, so programs must not rewrite it (a rewrite
would drop the comments). Values changed in the interface (Settings page) or with
``crapai config set`` go to a small machine-managed file next to it, ``project.overrides.yaml``.
It is layered **above** ``project.yaml`` and **below** environment variables and the command
line (precedence: command line > environment > overrides file > ``project.yaml`` > user
configuration > built-in defaults).

Deleting the file, or ``crapai config reset``, brings back exactly the values of ``project.yaml``.
Every change is validated against the full configuration model before it is written, so the file
can never make a project unusable.
"""

from __future__ import annotations

import copy
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from crapai.config import loader
from crapai.config.loader import deep_merge, read_yaml_mapping, validate_config
from crapai.errors import ConfigError
from crapai.project.atomic import atomic_write_text

logger = logging.getLogger(__name__)

OVERRIDES_NAME = loader.OVERRIDES_NAME
HEADER = (
    "# Settings changed in the interface or with 'crapai config set'. Machine-managed.\n"
    "# They win over project.yaml. Delete this file (or run 'crapai config reset') to undo them.\n"
)


def overrides_path(project_yaml: Path) -> Path:
    """The overrides file that belongs to ``project_yaml``."""
    return project_yaml.with_name(OVERRIDES_NAME)


def read_overrides(project_yaml: Path) -> dict[str, Any]:
    """The overrides as a nested mapping (empty if there is no file).

    Raises:
        ConfigError: (E203) if the file exists but is unreadable or not a mapping.
    """
    path = overrides_path(project_yaml)
    if not path.exists():
        return {}
    return read_yaml_mapping(path)


def _set_dotted(target: dict[str, Any], dotted: str, value: Any) -> None:
    keys = dotted.split(".")
    node = target
    for key in keys[:-1]:
        child = node.get(key)
        if not isinstance(child, dict):
            child = {}
            node[key] = child
        node = child
    node[keys[-1]] = value


def _unset_dotted(target: dict[str, Any], dotted: str) -> bool:
    """Remove one dotted key and any section that becomes empty; True if the key existed."""
    keys = dotted.split(".")
    trail: list[tuple[dict[str, Any], str]] = []
    node = target
    for key in keys[:-1]:
        child = node.get(key)
        if not isinstance(child, dict):
            return False
        trail.append((node, key))
        node = child
    if keys[-1] not in node:
        return False
    del node[keys[-1]]
    for parent, key in reversed(trail):
        if not parent[key]:
            del parent[key]
    return True


def write_overrides(project_yaml: Path, overrides: Mapping[str, Any]) -> None:
    """Validate ``project.yaml`` + ``overrides`` together and write the file atomically.

    An empty mapping removes the file. Nothing is written if the result would be invalid.

    Raises:
        ConfigError: E201/E203 if the combined configuration is invalid.
        StorageError: E401/E403 if the file cannot be written.
    """
    merged = deep_merge(read_yaml_mapping(project_yaml), dict(overrides))
    validate_config(merged, source=f"{project_yaml.name} + {OVERRIDES_NAME}")
    path = overrides_path(project_yaml)
    if not overrides:
        path.unlink(missing_ok=True)
        logger.info("Removed %s", path.name)
        return
    atomic_write_text(
        path, HEADER + yaml.safe_dump(dict(overrides), sort_keys=True, allow_unicode=True)
    )
    logger.info("Wrote %s (%d top-level section(s))", path.name, len(overrides))


def set_values(project_yaml: Path, values: Mapping[str, Any]) -> dict[str, Any]:
    """Set dotted keys (``llm.model``) in the overrides file; returns the new overrides.

    Raises:
        ConfigError: (E203) for an empty key or a value the configuration model rejects.
    """
    overrides = copy.deepcopy(read_overrides(project_yaml))
    for dotted, value in values.items():
        if not dotted.strip() or not all(dotted.split(".")):
            raise ConfigError(
                f"Invalid setting name '{dotted}': expected section.key",
                code="E203",
                hint="Example: llm.model or quality.short_abstract_words",
            )
        _set_dotted(overrides, dotted, value)
    write_overrides(project_yaml, overrides)
    return overrides


def reset_values(project_yaml: Path, keys: list[str] | None = None) -> list[str]:
    """Remove some dotted keys from the overrides (all of them if ``keys`` is empty or None).

    Returns:
        The keys that were removed.
    """
    overrides = copy.deepcopy(read_overrides(project_yaml))
    if not keys:
        removed = sorted(flatten(overrides))
        write_overrides(project_yaml, {})
        return removed
    removed = [key for key in keys if _unset_dotted(overrides, key)]
    write_overrides(project_yaml, overrides)
    return removed


def flatten(data: Mapping[str, Any], prefix: str = "") -> dict[str, Any]:
    """Nested mapping to ``{"section.key": value}``; lists and empty mappings are leaves."""
    flat: dict[str, Any] = {}
    for key, value in data.items():
        dotted = f"{prefix}{key}"
        if isinstance(value, Mapping) and value:
            flat.update(flatten(value, f"{dotted}."))
        else:
            flat[dotted] = value
    return flat


@dataclass(frozen=True)
class Setting:
    """One effective value and the layer it comes from.

    Attributes:
        key: Dotted name, for example ``quality.short_abstract_words``.
        value: The value that is in force.
        source: ``overrides``, ``environment``, ``project``, ``user`` or ``default``.
    """

    key: str
    value: Any
    source: str


def effective_settings(project_yaml: Path) -> list[Setting]:
    """Every setting with its value and source, sorted by key (``crapai config show``).

    Raises:
        ConfigError: if the combined configuration is invalid.
    """
    config = loader.resolve_config(project_yaml)
    effective = flatten(config.model_dump(mode="json", by_alias=True))
    layers = [
        ("overrides", flatten(read_overrides(project_yaml))),
        ("environment", flatten(loader.env_overrides())),
        ("project", flatten(read_yaml_mapping(project_yaml))),
    ]
    user = loader.default_user_config_path()
    if user.is_file():
        layers.append(("user", flatten(read_yaml_mapping(user))))
    settings: list[Setting] = []
    for key, value in sorted(effective.items()):
        source = next((name for name, flat in layers if key in flat), "default")
        settings.append(Setting(key, value, source))
    return settings
