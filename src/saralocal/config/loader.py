"""Load and validate ``project.yaml`` with precise error messages (plan chapters 16.3, 16.4, 26.4).

Errors are raised as :class:`saralocal.errors.ConfigError`. The message names the source and the
YAML path of every problem, and never repeats the offending value (it could be a pasted secret).
Code ``E201`` means a required field is missing, ``E203`` an invalid value, unknown key or a file
that cannot be read or parsed.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from saralocal.config.models import ProjectConfig
from saralocal.errors import ConfigError

logger = logging.getLogger(__name__)

CODE_MISSING = "E201"
CODE_INVALID = "E203"


def read_yaml_mapping(path: Path) -> dict[str, Any]:
    """Read a YAML file whose top level must be a mapping.

    Raises:
        ConfigError: (E203) if the file is missing, unreadable, not valid YAML or not a mapping.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ConfigError(
            f"Configuration file not found: {path}",
            code=CODE_INVALID,
            hint="Create it with 'init' or check the project folder.",
            details={"path": str(path)},
        ) from None
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigError(
            f"Configuration file cannot be read: {path} ({type(exc).__name__})",
            code=CODE_INVALID,
            hint="Save the file as UTF-8 and check the permissions.",
            details={"path": str(path)},
        ) from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f" (line {mark.line + 1}, column {mark.column + 1})" if mark else ""
        raise ConfigError(
            f"{path.name}: invalid YAML{where}",
            code=CODE_INVALID,
            hint="Check indentation and quotes around the reported position.",
            details={"path": str(path), "line": mark.line + 1 if mark else None},
        ) from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(
            f"{path.name}: the top level must be a mapping of settings",
            code=CODE_INVALID,
            details={"path": str(path)},
        )
    return data


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Return a new dict with ``override`` merged onto ``base``; nested mappings merge recursively.

    Lists and scalars from ``override`` replace those in ``base`` (a criteria list is not appended
    to). ``None`` in ``override`` is a real value (for example ``max_cost: null``) and replaces.
    """
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def config_error_from_validation(exc: ValidationError, source: str) -> ConfigError:
    """Turn a pydantic error into a :class:`ConfigError` naming YAML path and reason per problem.

    Missing required fields get code E201, everything else E203. The first problem decides the
    exception code; all problems are listed in the message and in ``details["problems"]``.
    """
    problems: list[dict[str, str]] = []
    for err in exc.errors(include_input=False, include_url=False):
        path = ".".join(str(part) for part in err["loc"]) or "(top level)"
        code = CODE_MISSING if err["type"] == "missing" else CODE_INVALID
        reason = _reason(err["type"], err["msg"])
        problems.append({"path": path, "code": code, "reason": reason})
    lines = [f"  - {p['path']}: {p['reason']} [{p['code']}]" for p in problems]
    message = f"{source}: {len(problems)} problem(s) in the configuration\n" + "\n".join(lines)
    return ConfigError(
        message,
        code=problems[0]["code"] if problems else CODE_INVALID,
        hint="Correct the listed fields in project.yaml.",
        details={"source": source, "problems": problems},
    )


def _reason(error_type: str, message: str) -> str:
    """Plain wording for the most common pydantic error types; otherwise pydantic's message."""
    if error_type == "missing":
        return "required field is missing"
    if error_type == "extra_forbidden":
        return "unknown setting (check the spelling)"
    # pydantic prefixes validator failures with "Value error, "; drop the noise.
    return message.removeprefix("Value error, ")


def validate_config(data: dict[str, Any], source: str = "project.yaml") -> ProjectConfig:
    """Validate a plain mapping against :class:`ProjectConfig`.

    Raises:
        ConfigError: E201 (missing field) or E203 (invalid value / unknown key).
    """
    try:
        return ProjectConfig.model_validate(data)
    except ValidationError as exc:
        raise config_error_from_validation(exc, source) from None


def load_project_config(path: Path) -> ProjectConfig:
    """Read and validate one ``project.yaml``.

    Layering with environment, command line and user config is added in :func:`resolve_config`.

    Raises:
        ConfigError: if the file cannot be read or fails validation.
    """
    data = read_yaml_mapping(path)
    config = validate_config(data, source=path.name)
    logger.info("Loaded project configuration from %s", path)
    return config
