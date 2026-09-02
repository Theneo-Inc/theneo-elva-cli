from __future__ import annotations

from pathlib import Path

import platformdirs

APP_NAME = "elva"
PROJECT_FILE = "elva.json"
USER_CONFIG_FILE = "config.json"


def config_dir() -> Path:
    return Path(platformdirs.user_config_dir(APP_NAME, appauthor=False))


def cache_dir() -> Path:
    return Path(platformdirs.user_cache_dir(APP_NAME, appauthor=False))


def crash_dir() -> Path:
    return cache_dir() / "crashes"


def user_config_file() -> Path:
    return config_dir() / USER_CONFIG_FILE


def find_project_file(start: Path) -> Path | None:
    """Walk up from start looking for elva.json, stopping at the repo root.

    The directory holding .git is checked and then the search ends, so a stray
    elva.json above someone's checkout is never picked up.
    """
    for directory in [start, *start.parents]:
        candidate = directory / PROJECT_FILE
        if candidate.is_file():
            return candidate
        if (directory / ".git").exists():
            break
    return None
