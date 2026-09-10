from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def _run(
    *args: str, cwd: Path, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    isolated = cwd / "xdgconfig"
    full = {
        **os.environ,
        "XDG_CONFIG_HOME": str(isolated),
        "WIN_PD_OVERRIDE_APPDATA": str(isolated),
        "WIN_PD_OVERRIDE_LOCAL_APPDATA": str(isolated),
        "PYTHON_KEYRING_BACKEND": "keyring.backends.fail.Keyring",
    }
    full.update(env or {})
    return subprocess.run(
        [sys.executable, "-m", "elva_cli", *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=cwd,
        env=full,
        stdin=subprocess.DEVNULL,
        timeout=30,
    )


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".git").mkdir()
    return root


def test_switch_without_argument_and_no_tty_exits_two(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    result = _run("workspace", "switch", cwd=root)
    assert result.returncode == 2
    assert "workspace name is required" in result.stderr


def test_switch_in_ci_never_prompts(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    result = _run("workspace", "switch", cwd=root, env={"CI": "true"})
    assert result.returncode == 2
    assert "workspace name is required" in result.stderr


def test_switch_rejects_object_id(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    oid = "0123456789abcdef01234567"
    result = _run("workspace", "switch", oid, cwd=root)
    assert result.returncode == 2
    assert "name or slug, not an id" in result.stderr


def test_switch_help_lists_global_flag(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    result = _run("workspace", "switch", "--help", cwd=root)
    assert result.returncode == 0
    assert "--global" in result.stdout
    assert json.dumps  # sanity
