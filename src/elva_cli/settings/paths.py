from __future__ import annotations

from pathlib import Path

import platformdirs

APP_NAME = "elva"


def cache_dir() -> Path:
    """Per-user cache location: XDG on Linux, ~/Library on macOS, %LOCALAPPDATA% on Windows."""
    return Path(platformdirs.user_cache_dir(APP_NAME, appauthor=False))


def crash_dir() -> Path:
    return cache_dir() / "crashes"
