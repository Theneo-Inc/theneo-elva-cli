"""Keep both pytest and child CLIs away from developer credentials/config."""

from __future__ import annotations

import os
import runpy
from pathlib import Path
from typing import TYPE_CHECKING

import platformdirs
import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture(scope="session", autouse=True)
def isolated_profile(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    support = Path(__file__).parent / "isolation"
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("CLI_TEST_ROOT", str(tmp_path_factory.mktemp("cli-profile")))
        patch.setenv("TERM", "xterm-256color")
        patch.setenv("PYTHON_KEYRING_BACKEND", "keyring.backends.fail.Keyring")
        patch.setenv(
            "PYTHONPATH", os.pathsep.join([str(support), os.environ.get("PYTHONPATH", "")])
        )
        # Record originals so pytest restores them after the same adapter that
        # Python automatically loads in child processes has run here.
        patch.setattr(platformdirs, "user_config_dir", platformdirs.user_config_dir)
        patch.setattr(platformdirs, "user_cache_dir", platformdirs.user_cache_dir)
        runpy.run_path(str(support / "sitecustomize.py"))
        yield
