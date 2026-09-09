"""Runs the whole command surface unattended and asserts nothing waits for input.

The command list is discovered from the real command tree, so a new command is
covered the day it is added rather than the day someone remembers to list it here.
"""

from __future__ import annotations

import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

from elva_cli.errors import ExitCode

if TYPE_CHECKING:
    from pathlib import Path

TIMEOUT = 30
NON_BLOCKING_EXIT_CODES = {ExitCode.OK, ExitCode.USAGE}
NEEDS_AUTH: frozenset[tuple[str, ...]] = frozenset({("auth", "login"), ("whoami",)})


def command_paths() -> list[tuple[str, ...]]:
    import typer
    import typer.main

    from elva_cli.main import app

    def walk(cmd: object, prefix: tuple[str, ...] = ()) -> list[tuple[str, ...]]:
        lister = getattr(cmd, "list_commands", None)
        if lister is None:
            return [prefix]
        ctx = typer.Context(cmd, info_name=prefix[-1] if prefix else "elva")  # type: ignore[arg-type]
        found: list[tuple[str, ...]] = []
        for name in lister(ctx):
            sub = cmd.get_command(ctx, name)  # type: ignore[attr-defined]
            if sub is not None:
                found.extend(walk(sub, (*prefix, name)))
        return found or [prefix]

    return walk(typer.main.get_command(app))


PATHS = command_paths()
VARIANTS = [
    pytest.param((), id="plain"),
    pytest.param(("--json",), id="json"),
    pytest.param(("--quiet",), id="quiet"),
    pytest.param(("--yes",), id="yes"),
]


def unattended(
    *args: str, cwd: Path, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[bytes]:
    """Run with stdin closed, so any prompt fails instead of waiting."""
    import os

    full = {
        **os.environ,
        **(env or {}),
        # Forced after `env` so a caller-supplied override can never disable
        # these safety defaults by accident.
        "XDG_CONFIG_HOME": str(cwd / "xdg"),
        "PYTHON_KEYRING_BACKEND": "keyring.backends.fail.Keyring",
    }
    return subprocess.run(
        [sys.executable, "-m", "elva_cli", *args],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
        cwd=cwd,
        env=full,
        timeout=TIMEOUT,
    )


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".git").mkdir()
    return root


def test_the_surface_was_actually_discovered() -> None:
    assert PATHS, "no commands discovered, the walk is broken"


@pytest.mark.parametrize("path", PATHS, ids=lambda p: " ".join(p) or "root")
@pytest.mark.parametrize("flags", VARIANTS)
def test_command_terminates_with_stdin_closed(
    path: tuple[str, ...], flags: tuple[str, ...], workdir: Path
) -> None:
    try:
        result = unattended(*flags, *path, cwd=workdir)
    except subprocess.TimeoutExpired:
        pytest.fail(f"'elva {' '.join((*flags, *path))}' blocked for {TIMEOUT}s with stdin closed")
    allowed = NON_BLOCKING_EXIT_CODES | ({ExitCode.AUTH} if path in NEEDS_AUTH else set())
    assert result.returncode in allowed, result.stderr.decode()


@pytest.mark.parametrize("path", PATHS, ids=lambda p: " ".join(p) or "root")
def test_command_terminates_in_ci(path: tuple[str, ...], workdir: Path) -> None:
    try:
        unattended(*path, cwd=workdir, env={"CI": "true"})
    except subprocess.TimeoutExpired:
        pytest.fail(f"'elva {' '.join(path)}' blocked for {TIMEOUT}s under CI=true")


def test_help_and_version_terminate(workdir: Path) -> None:
    for args in (("--help",), ("--version",), ()):
        try:
            unattended(*args, cwd=workdir)
        except subprocess.TimeoutExpired:
            pytest.fail(f"'elva {' '.join(args)}' blocked for {TIMEOUT}s")


def test_nothing_reads_stdin_when_it_is_a_pipe_with_no_data(workdir: Path) -> None:
    """A closed pipe is one thing, an open pipe that never delivers is another."""
    process = subprocess.Popen(
        [sys.executable, "-m", "elva_cli", "config", "list"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=workdir,
    )
    try:
        process.communicate(timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        process.kill()
        pytest.fail("config list waited on an open stdin pipe")
    assert process.returncode == 0
