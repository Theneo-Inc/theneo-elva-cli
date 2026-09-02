"""End-to-end exit codes, run as a real subprocess.

Uses `python -m elva_cli` rather than the `elva` script so the tests do not
depend on the console script being on PATH.
"""

from __future__ import annotations

import subprocess
import sys


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "elva_cli", *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_version_exits_ok() -> None:
    result = run("--version")
    assert result.returncode == 0
    assert result.stdout.startswith("elva ")


def test_help_exits_ok() -> None:
    assert run("--help").returncode == 0


def test_no_args_is_help_and_exits_usage() -> None:
    assert run().returncode == 2


def test_unknown_option_exits_usage() -> None:
    result = run("--definitely-not-an-option")
    assert result.returncode == 2


def test_unknown_command_exits_usage() -> None:
    assert run("definitely-not-a-command").returncode == 2


def test_no_traceback_ever_reaches_the_user() -> None:
    for args in ([], ["--definitely-not-an-option"], ["definitely-not-a-command"]):
        result = run(*args)
        assert "Traceback (most recent call last)" not in result.stderr
