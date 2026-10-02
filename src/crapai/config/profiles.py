"""Reusable settings profiles: save a project's review design, load it into another (ADR 0027).

Requested by the project lead, alongside full-text screening (ADR 0026) and more export formats.
There is no plan chapter for this; the design follows the project's existing patterns instead:

A profile is **not** a copy of ``project.yaml``: it holds only the portable parts of a project's
configuration -- the objectives, the criteria, the screening settings (including full-text mode,
ADR 0026) and the model/provider choice -- never a title, a file path, run history or anything
tied to one project folder. ``llm.api_key_env`` is only ever the *name* of an environment
variable (never a key), so a profile can hold it like ``project.yaml`` already does.

Profiles live in the user's configuration folder, the same one that already holds the optional
``config.yaml`` and the interface's ``ui_prefs.json`` (``default_user_config_path`` in
:mod:`crapai.config.loader`), not inside any project, so they are reusable across projects,
machines (if that folder is synced) and reviews.

Loading a profile writes its sections into the target project's ``project.overrides.yaml``
(:mod:`crapai.config.overrides`) -- exactly as ``crapai config set`` or the interface would:
``project.yaml`` itself is never touched, existing overrides outside the profile's sections are
kept, and the result is validated before anything is written.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field, ValidationError

from crapai.config.loader import (
    config_error_from_validation,
    deep_merge,
    default_user_config_path,
    read_yaml_mapping,
)
from crapai.config.models import Criteria, LlmSettings, ProjectConfig, ScreeningOptions, _Strict
from crapai.config.overrides import read_overrides, write_overrides
from crapai.errors import ConfigError
from crapai.project.atomic import atomic_write_text

logger = logging.getLogger(__name__)

PROFILE_SCHEMA = 1
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


class SettingsProfile(_Strict):
    """A reusable bundle of review design and model settings.

    Attributes:
        objectives: The review's objectives (plain sentences).
        criteria: Framework, custom fields, inclusion/exclusion criteria.
        screening: How the prompt is built and answers are read (includes full-text mode).
        llm: Provider, model and sampling settings (``api_key_env`` only ever names a variable).
    """

    schema_version: int = Field(default=PROFILE_SCHEMA, alias="schema")
    objectives: list[str] = Field(default_factory=list)
    criteria: Criteria
    screening: ScreeningOptions = Field(default_factory=ScreeningOptions)
    llm: LlmSettings = Field(default_factory=LlmSettings)


def profiles_dir() -> Path:
    """``~/.config/crapai/profiles/``: where saved settings profiles live."""
    return default_user_config_path().parent / "profiles"


def _validated_name(name: str) -> str:
    if not _NAME.match(name):
        raise ConfigError(
            f"Invalid profile name '{name}'",
            code="E203",
            hint="Use letters, digits, '-' or '_', starting with a letter or digit.",
            details={"name": name},
        )
    return name


def profile_path(name: str) -> Path:
    """The file a profile called ``name`` is (or would be) stored in.

    Raises:
        ConfigError: E203 if ``name`` is not a plain file-name-safe identifier.
    """
    return profiles_dir() / f"{_validated_name(name)}.yaml"


def save_profile(name: str, config: ProjectConfig) -> Path:
    """Save the portable parts of ``config`` as a named profile (overwrites one of the same name).

    Raises:
        ConfigError: E203 for an invalid name.
        StorageError: E401/E403 if the file cannot be written.
    """
    profile = SettingsProfile(
        objectives=list(config.objectives),
        criteria=config.criteria,
        screening=config.screening,
        llm=config.llm,
    )
    path = profile_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = profile.model_dump(mode="json", by_alias=True)
    atomic_write_text(path, yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
    logger.info("Saved settings profile '%s' to %s", name, path)
    return path


def load_profile(name: str) -> SettingsProfile:
    """Read and validate a saved profile.

    Raises:
        ConfigError: E203 if there is no such profile, or it is unreadable or invalid.
    """
    path = profile_path(name)
    if not path.is_file():
        raise ConfigError(
            f"There is no settings profile '{name}'",
            code="E203",
            hint="List the saved profiles with 'crapai profile list'.",
            details={"name": name, "path": str(path)},
        )
    data = read_yaml_mapping(path)
    try:
        return SettingsProfile.model_validate(data)
    except ValidationError as exc:
        raise config_error_from_validation(exc, path.name) from None


def list_profiles() -> list[str]:
    """Names of every saved profile, sorted (empty if the folder does not exist yet)."""
    folder = profiles_dir()
    if not folder.is_dir():
        return []
    return sorted(p.stem for p in folder.glob("*.yaml"))


def delete_profile(name: str) -> bool:
    """Delete a saved profile; True if it existed."""
    path = profile_path(name)
    existed = path.is_file()
    path.unlink(missing_ok=True)
    if existed:
        logger.info("Deleted settings profile '%s'", name)
    return existed


def apply_profile(project_yaml: Path, name: str) -> dict[str, Any]:
    """Load profile ``name`` into the project's overrides file; returns the sections written.

    ``project.yaml`` is never touched (undo with ``crapai config reset``); overrides outside the
    profile's four sections (``objectives``, ``criteria``, ``screening``, ``llm``) are kept.

    Raises:
        ConfigError: E203 if there is no such profile, or applying it would make the project's
            configuration invalid (for example an unknown prompt variant is not checked here).
    """
    profile = load_profile(name)
    new_sections = {
        "objectives": profile.objectives,
        "criteria": profile.criteria.model_dump(mode="json", by_alias=True),
        "screening": profile.screening.model_dump(mode="json", by_alias=True),
        "llm": profile.llm.model_dump(mode="json", by_alias=True),
    }
    merged = deep_merge(read_overrides(project_yaml), new_sections)
    write_overrides(project_yaml, merged)
    logger.info("Applied settings profile '%s' to %s", name, project_yaml.parent.name)
    return new_sections
