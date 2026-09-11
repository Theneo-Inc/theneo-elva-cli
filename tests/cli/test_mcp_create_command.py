"""Drives the real entry point. No case here reaches the network -- every
one is refused locally (bad usage, the publish confirmation gate, or not
signed in) before it would."""

from __future__ import annotations

from typing import TYPE_CHECKING

from elva_cli.errors import ExitCode

if TYPE_CHECKING:
    import subprocess
    from collections.abc import Callable

    Run = Callable[..., subprocess.CompletedProcess[str]]


class TestUsage:
    def test_no_name_and_no_from_is_usage(self, run: Run) -> None:
        result = run("mcp", "create")
        assert result.returncode == ExitCode.USAGE
        assert "--name" in result.stderr

    def test_from_combined_with_a_flag_is_usage(self, run: Run, tmp_path: object) -> None:
        from pathlib import Path

        config = Path(str(tmp_path)) / "config.json"
        config.write_text('{"mcpName": "x"}')
        result = run("mcp", "create", "--name", "x", "--from", str(config))
        assert result.returncode == ExitCode.USAGE
        assert "--from" in result.stderr

    def test_bad_auth_type_is_usage(self, run: Run) -> None:
        result = run("mcp", "create", "--name", "x", "--auth-type", "magic")
        assert result.returncode == ExitCode.USAGE

    def test_unattended_without_yes_is_usage_before_any_auth_check(self, run: Run) -> None:
        """stdin is closed by `run` (see conftest.py) -- this must fail on the
        publish confirmation gate, not hang and not reach the network."""
        result = run("mcp", "create", "--name", "x")
        assert result.returncode == ExitCode.USAGE
        assert "--yes" in result.stderr


class TestDryRunSkipsTheConfirmationGate:
    def test_dry_run_unattended_reaches_the_auth_check_instead_of_usage(self, run: Run) -> None:
        """No --yes needed for --dry-run since nothing is created -- this
        should get past the confirmation gate and fail on credentials
        instead, proving the gate was actually skipped rather than just
        happening to pass. --collection is passed explicitly so the only
        thing standing between this invocation and a network call is auth."""
        result = run("--collection", "petstore", "mcp", "create", "--name", "x", "--dry-run")
        assert result.returncode == ExitCode.AUTH


class TestDraftSkipsTheConfirmationGate:
    def test_draft_unattended_reaches_the_auth_check_instead_of_usage(self, run: Run) -> None:
        """A draft isn't publicly reachable, so --draft gets the same pass
        through the confirmation gate as --dry-run does."""
        result = run("--collection", "petstore", "mcp", "create", "--name", "x", "--draft")
        assert result.returncode == ExitCode.AUTH

    def test_dry_run_combined_with_draft_is_usage(self, run: Run) -> None:
        result = run("mcp", "create", "--name", "x", "--dry-run", "--draft")
        assert result.returncode == ExitCode.USAGE
        assert "--dry-run" in result.stderr
        assert "--draft" in result.stderr


class TestErrorsGoToStderr:
    def test_json_mode_keeps_stdout_clean_on_failure(self, run: Run) -> None:
        result = run(
            "--json", "--collection", "petstore", "mcp", "create", "--name", "x", "--dry-run"
        )
        assert result.returncode == ExitCode.AUTH
        assert result.stdout == ""
        assert "ELVA_AUTH" in result.stderr
