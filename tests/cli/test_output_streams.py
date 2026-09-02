"""Stream and colour behaviour, checked against the real process."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

ESC = b"\x1b"


def run(
    *args: str, cwd: Path, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[bytes]:
    full = {**os.environ, "XDG_CONFIG_HOME": str(cwd / "xdg")}
    full.pop("NO_COLOR", None)
    full.update(env or {})
    return subprocess.run(
        [sys.executable, "-m", "elva_cli", *args],
        capture_output=True,
        check=False,
        cwd=cwd,
        env=full,
    )


def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".git").mkdir()
    return root


def test_data_on_stdout_and_stderr_stays_empty(tmp_path: Path) -> None:
    result = run("config", "list", cwd=repo(tmp_path))
    assert result.returncode == 0
    assert result.stdout
    assert result.stderr == b""


def test_json_is_parseable_and_has_no_escape_codes(tmp_path: Path) -> None:
    result = run("--json", "config", "list", cwd=repo(tmp_path))
    assert ESC not in result.stdout
    json.loads(result.stdout)


def test_json_stays_plain_even_when_colour_is_forced(tmp_path: Path) -> None:
    result = run("--color", "--json", "config", "list", cwd=repo(tmp_path))
    assert ESC not in result.stdout
    json.loads(result.stdout)


def test_forced_colour_styles_human_output(tmp_path: Path) -> None:
    result = run("--color", "config", "list", cwd=repo(tmp_path))
    assert ESC in result.stdout


def test_no_color_flag_strips_styling(tmp_path: Path) -> None:
    result = run("--no-color", "config", "list", cwd=repo(tmp_path))
    assert ESC not in result.stdout


def test_no_color_env_strips_styling(tmp_path: Path) -> None:
    result = run("config", "list", cwd=repo(tmp_path), env={"NO_COLOR": "1"})
    assert ESC not in result.stdout


def test_explicit_color_flag_beats_no_color_env(tmp_path: Path) -> None:
    result = run("--color", "config", "list", cwd=repo(tmp_path), env={"NO_COLOR": "1"})
    assert ESC in result.stdout


def test_errors_never_touch_stdout(tmp_path: Path) -> None:
    root = repo(tmp_path)
    (root / "elva.json").write_bytes(b"{oops")
    result = run("config", "list", cwd=root)
    assert result.returncode == 2
    assert result.stdout == b""
    assert b"ELVA_CONFIG" in result.stderr


def test_both_modes_describe_the_same_state(tmp_path: Path) -> None:
    """The point of one Result: --json cannot drift from what a person sees."""
    root = repo(tmp_path)
    (root / "elva.json").write_text('{"workspace": "payments"}', encoding="utf-8")

    human = run("config", "list", cwd=root).stdout.decode()
    machine = json.loads(run("--json", "config", "list", cwd=root).stdout)

    values = {s["key"]: (s["value"], s["origin"]) for s in machine["settings"]}
    assert values["workspace"] == ("payments", "project")
    assert "payments" in human
    assert "project" in human
