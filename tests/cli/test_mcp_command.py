"""Drives the real entry point. Nothing here reaches the network -- every
case is one the CLI refuses locally (not signed in) before it would."""

from __future__ import annotations

from typing import TYPE_CHECKING

from elva_cli.errors import ExitCode

if TYPE_CHECKING:
    import subprocess
    from collections.abc import Callable

    Run = Callable[..., subprocess.CompletedProcess[str]]


class TestAuth:
    def test_list_without_credentials_is_auth(self, run: Run) -> None:
        result = run("mcp", "list")
        assert result.returncode == ExitCode.AUTH
        assert "not logged in" in result.stderr

    def test_show_without_credentials_is_auth(self, run: Run) -> None:
        result = run("mcp", "show", "some-slug")
        assert result.returncode == ExitCode.AUTH
        assert "not logged in" in result.stderr


class TestUsage:
    def test_bare_mcp_lists_its_subcommands(self, run: Run) -> None:
        result = run("mcp")
        assert result.returncode == ExitCode.USAGE
        assert "list" in result.stdout
        assert "show" in result.stdout

    def test_show_without_a_slug_is_usage(self, run: Run) -> None:
        result = run("mcp", "show")
        assert result.returncode == ExitCode.USAGE


class TestErrorsGoToStderr:
    def test_json_mode_keeps_stdout_clean_on_failure(self, run: Run) -> None:
        result = run("--json", "mcp", "list")
        assert result.returncode == ExitCode.AUTH
        assert result.stdout == ""
        assert "ELVA_AUTH" in result.stderr
