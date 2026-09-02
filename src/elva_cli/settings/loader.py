from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError as PydanticValidationError

from elva_cli.errors import ConfigError
from elva_cli.settings import paths
from elva_cli.settings.models import Settings

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

ENV_PREFIX = "ELVA_"

_ENV_KEYS = {
    "ELVA_BASE_URL": "base_url",
    "ELVA_PROFILE": "profile",
    "ELVA_WORKSPACE": "workspace",
    "ELVA_COLLECTION": "collection",
    "ELVA_TIMEOUT": "timeout",
}

DEFAULT_PROFILE = "default"


@dataclass(frozen=True)
class ConfigFile:
    kind: str
    path: Path
    exists: bool


@dataclass(frozen=True)
class Resolution:
    settings: Settings
    origins: dict[str, str]
    files: tuple[ConfigFile, ...]
    profiles: tuple[str, ...]


def _read_json(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path} must contain a JSON object")
    return data


def _coerce(field: str, raw: str, source: str) -> Any:
    if field == "timeout":
        try:
            return float(raw)
        except ValueError:
            raise ConfigError(f"{source} must be a number, got {raw!r}") from None
    return raw


def _split_profiles(data: dict[str, Any], path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    profiles = data.pop("profiles", {})
    if not isinstance(profiles, dict):
        raise ConfigError(f'"profiles" in {path} must be an object')
    return data, profiles


def resolve(
    *,
    overrides: Mapping[str, Any] | None = None,
    env: Mapping[str, str],
    cwd: Path,
) -> Resolution:
    """Merge every configuration source into one frozen Settings.

    Highest precedence first, and the first layer carrying a field wins.
    """
    flags = {k: v for k, v in (overrides or {}).items() if v is not None}

    env_layer: dict[str, Any] = {}
    for key, field in _ENV_KEYS.items():
        raw = env.get(key)
        if raw:
            env_layer[field] = _coerce(field, raw, key)

    user_path = paths.user_config_file()
    user_layer, profiles = (
        _split_profiles(_read_json(user_path), user_path) if user_path.is_file() else ({}, {})
    )

    project_path = paths.find_project_file(cwd)
    project_layer = _read_json(project_path) if project_path else {}
    project_layer.pop("profiles", None)

    selected = (
        flags.get("profile")
        or env_layer.get("profile")
        or project_layer.get("profile")
        or user_layer.get("profile")
        or DEFAULT_PROFILE
    )
    overlay = profiles.get(selected, {})
    if not isinstance(overlay, dict):
        raise ConfigError(f'profile "{selected}" must be an object')
    if selected != DEFAULT_PROFILE and selected not in profiles:
        raise ConfigError(
            f'unknown profile "{selected}"',
            hint=f"Profiles defined in {user_path}: {', '.join(sorted(profiles)) or 'none'}",
        )

    layers: list[tuple[str, Mapping[str, Any]]] = [
        ("flag", flags),
        ("env", env_layer),
        ("project", project_layer),
        (f"profile:{selected}", overlay),
        ("user", user_layer),
    ]

    merged: dict[str, Any] = {}
    origins: dict[str, str] = {}
    for name, layer in layers:
        for field, value in layer.items():
            if field not in merged:
                merged[field] = value
                origins[field] = name

    try:
        settings = Settings(**merged)
    except PydanticValidationError as exc:
        first = exc.errors()[0]
        field = str(first["loc"][0]) if first["loc"] else "config"
        where = origins.get(field, "default")
        raise ConfigError(f"invalid setting {field!r} from {where}: {first['msg']}") from exc

    for field in Settings.model_fields:
        origins.setdefault(field, "default")

    files = (
        ConfigFile("project", project_path or cwd / paths.PROJECT_FILE, project_path is not None),
        ConfigFile("user", user_path, user_path.is_file()),
    )
    return Resolution(
        settings=settings,
        origins=origins,
        files=files,
        profiles=tuple(sorted(profiles)),
    )
