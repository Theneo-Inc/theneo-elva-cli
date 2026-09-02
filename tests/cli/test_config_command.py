from __future__ import annotations

import json
import subprocess
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def run(
    *args: str, cwd: Path, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    import os

    full = {**os.environ, "XDG_CONFIG_HOME": str(cwd / "xdgconfig")}
    full.update(env or {})
    return subprocess.run(
        [sys.executable, "-m", "elva_cli", *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=cwd,
        env=full,
    )


def project(tmp_path: Path, data: dict[str, object] | None = None) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".git").mkdir()
    if data is not None:
        (root / "elva.json").write_text(json.dumps(data), encoding="utf-8")
    return root


def test_config_path_lists_every_file_even_when_absent(tmp_path: Path) -> None:
    root = project(tmp_path)
    result = run("config", "path", cwd=root)
    assert result.returncode == 0
    assert "project config" in result.stdout
    assert "user config" in result.stdout
    assert "(absent)" in result.stdout


def test_config_path_marks_an_existing_project_file(tmp_path: Path) -> None:
    root = project(tmp_path, {"workspace": "payments"})
    result = run("config", "path", cwd=root)
    assert "(found)" in result.stdout
    assert "elva.json" in result.stdout


def test_config_list_shows_value_and_origin(tmp_path: Path) -> None:
    root = project(tmp_path, {"workspace": "payments"})
    result = run("config", "list", cwd=root)
    assert result.returncode == 0
    lines = {line.split()[0]: line for line in result.stdout.splitlines() if line.strip()}
    assert "project" in lines["workspace"]
    assert "payments" in lines["workspace"]
    assert "default" in lines["base_url"]


def test_config_list_reflects_a_flag(tmp_path: Path) -> None:
    root = project(tmp_path, {"workspace": "payments"})
    result = run("--workspace", "other", "config", "list", cwd=root)
    assert "other" in result.stdout
    assert "flag" in result.stdout


def test_config_list_reflects_env(tmp_path: Path) -> None:
    root = project(tmp_path)
    result = run("config", "list", cwd=root, env={"ELVA_BASE_URL": "https://env.example.com"})
    assert "https://env.example.com" in result.stdout
    assert "env" in result.stdout


def test_bad_config_reports_a_coded_error(tmp_path: Path) -> None:
    root = project(tmp_path)
    (root / "elva.json").write_text("{oops", encoding="utf-8")
    result = run("config", "list", cwd=root)
    assert result.returncode == 2
    assert "ELVA_CONFIG" in result.stderr
    assert "Traceback" not in result.stderr
