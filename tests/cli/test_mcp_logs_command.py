"""Drives the real entry point. No case here reaches the network -- every
one is refused locally (bad usage, not signed in) before it would."""

from __future__ import annotations

from typing import TYPE_CHECKING

from elva_cli.errors import ExitCode

if TYPE_CHECKING:
    import subprocess
    from collections.abc import Callable

    Run = Callable[..., subprocess.CompletedProcess[str]]


class TestUsage:
    def test_logs_without_a_slug_is_usage(self, run: Run) -> None:
        result = run("mcp", "logs")
        assert result.returncode == ExitCode.USAGE

    def test_follow_with_page_is_usage_before_any_network_call(self, run: Run) -> None:
        result = run("mcp", "logs", "some-slug", "--follow", "--page", "2")
        assert result.returncode == ExitCode.USAGE
        assert "--follow" in result.stderr

    def test_limit_above_the_cap_is_refused_locally(self, run: Run) -> None:
        result = run("mcp", "logs", "some-slug", "--limit", "5000")
        assert result.returncode == ExitCode.USAGE


class TestAuth:
    def test_logs_without_credentials_is_auth(self, run: Run) -> None:
        result = run("mcp", "logs", "some-slug")
        assert result.returncode == ExitCode.AUTH
        assert "not logged in" in result.stderr

    def test_follow_without_credentials_is_auth_and_terminates(self, run: Run) -> None:
        """--follow must not poll forever just because it never got past
        authentication -- stdin is closed by `run` (see conftest.py), so a
        regression that entered the poll loop unauthenticated would hang
        the subprocess until the harness's own timeout kills it."""
        result = run("mcp", "logs", "some-slug", "--follow")
        assert result.returncode == ExitCode.AUTH


class TestErrorsGoToStderr:
    def test_json_mode_keeps_stdout_clean_on_failure(self, run: Run) -> None:
        result = run("--json", "mcp", "logs", "some-slug")
        assert result.returncode == ExitCode.AUTH
        assert result.stdout == ""
        assert "ELVA_AUTH" in result.stderr
