from __future__ import annotations

import subprocess
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def run(
    *args: str, cwd: Path, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Forces the fail keyring backend so this never touches whatever
    machine runs the tests' real OS keyring -- see test_never_blocks.py's
    unattended() for the same reasoning."""
    import os

    full = {
        **os.environ,
        **(env or {}),
        # Forced after `env` so a caller-supplied override can never disable
        # these safety defaults by accident.
        "XDG_CONFIG_HOME": str(cwd / "xdgconfig"),
        "PYTHON_KEYRING_BACKEND": "keyring.backends.fail.Keyring",
    }
    return subprocess.run(
        [sys.executable, "-m", "elva_cli", *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=cwd,
        env=full,
    )


def workdir(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".git").mkdir()
    return root


def test_logout_with_nothing_stored_says_so(tmp_path: Path) -> None:
    root = workdir(tmp_path)
    result = run("auth", "logout", cwd=root)
    assert result.returncode == 0
    assert "weren't signed in" in result.stdout

    result = run("auth", "logout", cwd=root, env={"ELVA_TOKEN": "anything"})
    assert result.returncode == 0
    assert "ELVA_TOKEN" in result.stderr
