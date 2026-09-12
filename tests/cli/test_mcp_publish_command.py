"""Drives the real entry point. Every case here is refused locally (bad
usage or the publish confirmation gate) before it would reach the network."""

from __future__ import annotations

from typing import TYPE_CHECKING

from elva_cli.errors import ExitCode

if TYPE_CHECKING:
    import subprocess
    from collections.abc import Callable

    Run = Callable[..., subprocess.CompletedProcess[str]]


class TestUsage:
    def test_no_slug_is_usage(self, run: Run) -> None:
        result = run("mcp", "publish")
        assert result.returncode == ExitCode.USAGE

    def test_unattended_without_yes_is_usage_before_any_network_call(self, run: Run) -> None:
        """stdin is closed by `run` (see conftest.py) -- this is the same
        confirmation boundary `mcp create` uses, now shared by `publish`."""
        result = run("mcp", "publish", "my-api")
        assert result.returncode == ExitCode.USAGE
        assert "--yes" in result.stderr


class TestErrorsGoToStderr:
    def test_json_mode_keeps_stdout_clean_on_failure(self, run: Run) -> None:
        result = run("--json", "mcp", "publish", "my-api")
        assert result.returncode == ExitCode.USAGE
        assert result.stdout == ""
