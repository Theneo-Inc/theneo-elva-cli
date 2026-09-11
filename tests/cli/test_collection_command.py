"""Drives the real entry point, so the wiring is covered as well as the flow.

Nothing here reaches the network: `collection list` needs credentials before it
can call the API, so every case is one the CLI settles locally first.

--workspace and --json are global options on the root callback, so they go
*before* the subcommand -- `elva --json collection list`, not the other way.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from elva_cli.errors import ExitCode

if TYPE_CHECKING:
    import subprocess
    from collections.abc import Callable

    Run = Callable[..., subprocess.CompletedProcess[str]]


def test_the_command_group_is_registered(run: Run) -> None:
    result = run("collection")
    assert result.returncode == ExitCode.USAGE
    assert "list" in result.stdout
    assert "show" in result.stdout
    assert "endpoints" in result.stdout


def test_show_needs_a_collection_argument(run: Run) -> None:
    result = run("collection", "show")
    assert result.returncode == ExitCode.USAGE


def test_show_not_logged_in_is_auth(run: Run) -> None:
    result = run("collection", "show", "payments-api")
    assert result.returncode == ExitCode.AUTH
    assert "not logged in" in result.stderr


def test_show_json_mode_keeps_stdout_clean_on_failure(run: Run) -> None:
    result = run("--json", "collection", "show", "payments-api")
    assert result.returncode == ExitCode.AUTH
    assert result.stdout == ""
    assert "ELVA_AUTH" in result.stderr


def test_endpoints_needs_a_collection_argument(run: Run) -> None:
    result = run("collection", "endpoints")
    assert result.returncode == ExitCode.USAGE


def test_endpoints_not_logged_in_is_auth(run: Run) -> None:
    result = run("collection", "endpoints", "payments-api")
    assert result.returncode == ExitCode.AUTH
    assert "not logged in" in result.stderr


def test_endpoints_json_mode_keeps_stdout_clean_on_failure(run: Run) -> None:
    result = run("--json", "collection", "endpoints", "payments-api")
    assert result.returncode == ExitCode.AUTH
    assert result.stdout == ""
    assert "ELVA_AUTH" in result.stderr


def test_it_shows_up_in_top_level_help(run: Run) -> None:
    result = run("--help")
    assert result.returncode == ExitCode.OK
    assert "collection" in result.stdout


def test_not_logged_in_is_auth(run: Run) -> None:
    result = run("collection", "list")
    assert result.returncode == ExitCode.AUTH
    assert "not logged in" in result.stderr


def test_json_mode_keeps_stdout_clean_on_failure(run: Run) -> None:
    result = run("--json", "collection", "list")
    assert result.returncode == ExitCode.AUTH
    assert result.stdout == ""
    assert "ELVA_AUTH" in result.stderr
