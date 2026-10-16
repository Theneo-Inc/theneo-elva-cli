"""Subprocess test isolation on every OS, including macOS (which ignores XDG)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

if os.environ.get("CLI_TEST_ROOT"):
    import platformdirs

    _config = platformdirs.user_config_dir
    _cache = platformdirs.user_cache_dir

    def config(appname: str | None = None, *args: Any, **kwargs: Any) -> str:
        if appname == "elva":
            root = os.environ.get("XDG_CONFIG_HOME", os.environ["CLI_TEST_ROOT"])
            return str(Path(root) / "elva")
        return _config(appname, *args, **kwargs)

    def cache(appname: str | None = None, *args: Any, **kwargs: Any) -> str:
        if appname == "elva":
            return str(Path(os.environ["CLI_TEST_ROOT"]) / "cache")
        return _cache(appname, *args, **kwargs)

    platformdirs.user_config_dir = config
    platformdirs.user_cache_dir = cache
