"""Load and validate ``project.yaml`` with precise error messages (plan chapters 16.3, 16.4, 26.4).

Errors are raised as :class:`crapai.errors.ConfigError`. The message names the source and the
YAML path of every problem, and never repeats the offending value (it could be a pasted secret).
Code ``E201`` means a required field is missing, ``E203`` an invalid value, unknown key or a file
that cannot be read or parsed.
"""

from __future__ import annotations

import copy
import functools
import logging
import os
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from crapai.branding import ENV_PREFIX
from crapai.config.models import ProjectConfig
from crapai.errors import ConfigError, SaraError

logger = logging.getLogger(__name__)

CODE_MISSING = "E201"
CODE_INVALID = "E203"
ENV_NESTING = "__"


@functools.lru_cache(maxsize=64)
def _parse_yaml(text: str) -> Any:
    """Parse YAML text; the result is cached by content (one ``check`` reads the file many times).

    Callers get a deep copy, so nobody can change the cached value. Invalid YAML raises and is
    not cached.
    """
    return yaml.safe_load(text)


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
        data = copy.deepcopy(_parse_yaml(text))
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
        hint="Correct the listed fields (in project.yaml, or in the layer named above).",
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


def describe_config_problem(error: SaraError) -> str:
    """One line that says what is wrong: the first problem as ``path: reason`` (+ how many more).

    Falls back to the first line of the message for errors without a problem list (for example an
    unreadable file).
    """
    problems = error.details.get("problems")
    if isinstance(problems, list) and problems:
        first = problems[0]
        text = f"{first['path']}: {first['reason']}"
        return text if len(problems) == 1 else f"{text} (+{len(problems) - 1} more)"
    return str(error).splitlines()[0]


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

    Environment, command line and user config are layered on top by :func:`resolve_config`.

    Raises:
        ConfigError: if the file cannot be read or fails validation.
    """
    data = read_yaml_mapping(path)
    config = validate_config(data, source=path.name)
    logger.info("Loaded project configuration from %s", path)
    return config


def default_user_config_path() -> Path:
    """Location of the optional per-user configuration (plan chapter 16.3)."""
    return Path.home() / ".config" / "crapai" / "config.yaml"


def _set_nested(target: dict[str, Any], keys: list[str], value: Any) -> None:
    """Set ``value`` at the path ``keys`` inside ``target``, creating mappings as needed."""
    node = target
    for key in keys[:-1]:
        child = node.get(key)
        if not isinstance(child, dict):
            child = {}
            node[key] = child
        node = child
    node[keys[-1]] = value


def _parse_scalar(text: str) -> Any:
    """Interpret an override string like YAML would (``5`` -> 5, ``true`` -> True).

    Text that is not valid YAML stays a plain string.
    """
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError:
        return text


def env_overrides(environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Collect settings from environment variables named ``CRAPAI_<SECTION>__<KEY>``.

    Example: ``CRAPAI_LLM__MODEL=gpt-4o`` sets ``llm.model``. Only variables with the nesting
    separator ``__`` are used, so unrelated ``CRAPAI_*`` variables are ignored. Names are
    lower-cased. The naming scheme is an implementation choice; the plan only fixes the
    precedence.
    """
    environ = os.environ if environ is None else environ
    result: dict[str, Any] = {}
    for name, raw in environ.items():
        if not name.startswith(ENV_PREFIX) or ENV_NESTING not in name:
            continue
        keys = [part.lower() for part in name.removeprefix(ENV_PREFIX).split(ENV_NESTING)]
        if not all(keys):
            continue
        _set_nested(result, keys, _parse_scalar(raw))
    return result


def parse_cli_overrides(pairs: Iterable[str]) -> dict[str, Any]:
    """Turn ``["llm.model=gpt-4o", "limits.rpm=100"]`` into a nested mapping.

    Raises:
        ConfigError: (E203) if an entry has no ``=`` or an empty key.
    """
    result: dict[str, Any] = {}
    for pair in pairs:
        key, sep, raw = pair.partition("=")
        keys = key.strip().split(".")
        if not sep or not all(keys):
            raise ConfigError(
                f"Invalid override {key.strip() or pair!r}: expected section.key=value",
                code=CODE_INVALID,
                hint="Example: --set llm.model=gpt-4o",
            )
        _set_nested(result, keys, _parse_scalar(raw))
    return result


def resolve_config(
    project_path: Path,
    *,
    cli: Mapping[str, Any] | None = None,
    environ: Mapping[str, str] | None = None,
    user_config_path: Path | None = None,
) -> ProjectConfig:
    """Load a project configuration with the precedence of plan chapter 16.3.

    CLI argument > environment variable > ``project.yaml`` > user configuration > built-in default.
    The built-in defaults are the field defaults of :class:`ProjectConfig`. The user configuration
    is optional and may be partial; it is skipped when the file does not exist.

    Args:
        project_path: The project's ``project.yaml``.
        cli: Nested overrides from the command line (see :func:`parse_cli_overrides`).
        environ: Environment to read (defaults to ``os.environ``); injectable for tests.
        user_config_path: Override for the user configuration location.

    Raises:
        ConfigError: if any layer cannot be read or the merged result is invalid.
    """
    user_path = user_config_path or default_user_config_path()
    merged: dict[str, Any] = {}
    if user_path.is_file():
        merged = deep_merge(merged, read_yaml_mapping(user_path))
    merged = deep_merge(merged, read_yaml_mapping(project_path))
    merged = deep_merge(merged, env_overrides(environ))
    merged = deep_merge(merged, dict(cli or {}))
    layers = [
        name
        for name, present in (
            ("user configuration", bool(user_path.is_file())),
            ("environment variables", bool(env_overrides(environ))),
            ("command line", bool(cli)),
        )
        if present
    ]
    label = project_path.name + (f" (merged with: {', '.join(layers)})" if layers else "")
    config = validate_config(merged, source=label)
    logger.info("Resolved project configuration for %s", project_path)
    return config
