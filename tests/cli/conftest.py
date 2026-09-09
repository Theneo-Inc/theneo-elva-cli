"""Shared harness for the tests that drive the real `elva` entry point as a
subprocess.

`run` forces the fail keyring backend and points `XDG_CONFIG_HOME` at a
throwaway directory, so a subprocess test never reads or writes the OS
keyring or the developer's real config -- see test_never_blocks.py's
unattended() for the same reasoning. It also passes `timeout=` and closes
stdin, so a regression that starts blocking fails the test fast instead of
hanging CI.
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

TIMEOUT = 30


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".git").mkdir()
    return root


@pytest.fixture
def run(workdir: Path) -> Callable[..., subprocess.CompletedProcess[str]]:
    def _run(
        *args: str, cwd: Path | None = None, env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        base = workdir if cwd is None else cwd
        full = {
            **os.environ,
            **(env or {}),
            # Forced after `env` so a caller-supplied override can never
            # disable these safety defaults by accident.
            "XDG_CONFIG_HOME": str(base / "xdgconfig"),
            "PYTHON_KEYRING_BACKEND": "keyring.backends.fail.Keyring",
        }
        return subprocess.run(
            [sys.executable, "-m", "elva_cli", *args],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
            cwd=base,
            env=full,
            timeout=TIMEOUT,
        )

    return _run
