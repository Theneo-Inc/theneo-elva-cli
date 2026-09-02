"""Use cases for inspecting configuration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from elva_cli.settings import paths

if TYPE_CHECKING:
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
