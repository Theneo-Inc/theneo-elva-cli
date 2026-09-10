"""Use cases for inspecting configuration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from elva_cli.errors import ConfigError
from elva_cli.settings import paths

if TYPE_CHECKING:
    from pathlib import Path

    from elva_cli.settings.loader import Resolution


@dataclass(frozen=True)
class ConfigFileInfo:
    kind: str
    path: str
    exists: bool


@dataclass(frozen=True)
class ConfigPaths:
    config_dir: str
    cache_dir: str
    files: list[ConfigFileInfo] = field(default_factory=list)


@dataclass(frozen=True)
class SettingValue:
    key: str
    value: Any
    origin: str


@dataclass(frozen=True)
class ConfigValues:
    profile: str
    settings: list[SettingValue] = field(default_factory=list)
    profiles: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SettingRead:
    key: str
    value: Any


@dataclass(frozen=True)
class ConfigWrite:
    action: str
    target: str
    path: str
    key: str
    value: Any


def describe_paths(resolution: Resolution) -> ConfigPaths:
    """Report every location the CLI consulted, whether or not it existed."""
    return ConfigPaths(
        config_dir=str(paths.config_dir()),
        cache_dir=str(paths.cache_dir()),
        files=[
            ConfigFileInfo(kind=f.kind, path=str(f.path), exists=f.exists) for f in resolution.files
        ],
    )


def describe_values(resolution: Resolution) -> ConfigValues:
    """Report each resolved setting alongside the layer that set it."""
    settings = resolution.settings
    return ConfigValues(
        profile=settings.profile,
        settings=[
            SettingValue(
                key=key,
                value=getattr(settings, key),
                origin=resolution.origins[key],
            )
            for key in sorted(type(settings).model_fields)
        ],
        profiles=list(resolution.profiles),
    )


def read_setting(resolution: Resolution, key: str) -> SettingRead:
    from elva_cli.settings.writer import KNOWN_KEYS

    if key not in KNOWN_KEYS:
        valid = ", ".join(sorted(KNOWN_KEYS))
        raise ConfigError(f"unknown key {key!r}", hint=f"valid keys: {valid}")
    value = getattr(resolution.settings, key)
    if value is None:
        raise ConfigError(f"{key!r} is not set", hint=f"Set it with 'elva config set {key} <value>'.")
    return SettingRead(key=key, value=value)


def write_setting(*, cwd: Path, key: str, value: str, use_global: bool) -> ConfigWrite:
    from elva_cli.settings.writer import resolve_target, set_value

    target = resolve_target(use_global=use_global, cwd=cwd)
    stored = set_value(key=key, value=value, target=target)
    return ConfigWrite(
        action="set", target=target.kind, path=str(target.path), key=key, value=stored
    )


def clear_setting(*, cwd: Path, key: str, use_global: bool) -> ConfigWrite:
    from elva_cli.settings.writer import resolve_target, unset_value

    target = resolve_target(use_global=use_global, cwd=cwd)
    unset_value(key=key, target=target)
    return ConfigWrite(
        action="unset", target=target.kind, path=str(target.path), key=key, value=None
    )
