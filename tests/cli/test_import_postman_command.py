"""Drives the real entry point for `elva import postman`.

Nothing here reaches Postman or Elva: every case is one the CLI settles before
it would send anything, or one that stops at not being signed in.

Note the argument order. --workspace is a global option on the root callback,
so it goes *before* the subcommand.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from elva_cli.errors import ExitCode

if TYPE_CHECKING:
    import subprocess
    from collections.abc import Callable
    from pathlib import Path

    Run = Callable[..., subprocess.CompletedProcess[str]]

KEY = "PMAK-NOT-A-REAL-KEY-fixture-only-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
SIGNED_OUT = {"ELVA_POSTMAN_API_KEY": KEY}


class TestTheKeyIsNeverAFlag:
    """argv lands in shell history and in `ps` output."""

    def test_there_is_no_api_key_option(self, run: Run) -> None:
        result = run("import", "postman", "--api-key", KEY)
        assert result.returncode == ExitCode.USAGE
        assert "No such option" in result.stderr

    def test_the_help_points_at_the_environment_variable_instead(self, run: Run) -> None:
        result = run("import", "postman", "--help")
        assert result.returncode == ExitCode.OK
        assert "ELVA_POSTMAN_API_KEY" in result.stdout


class TestWithoutAKey:
    def test_no_key_and_no_terminal_is_usage(self, run: Run) -> None:
        result = run("import", "postman")
        assert result.returncode == ExitCode.USAGE
        assert "ELVA_POSTMAN_API_KEY is required" in result.stderr

    def test_listing_without_a_key_is_usage_too(self, run: Run) -> None:
        result = run("import", "postman", "--list")
        assert result.returncode == ExitCode.USAGE
        assert "ELVA_POSTMAN_API_KEY" in result.stderr

    def test_an_empty_variable_says_so(self, run: Run) -> None:
        result = run("import", "postman", env={"ELVA_POSTMAN_API_KEY": ""})
        assert result.returncode == ExitCode.USAGE
        assert "no Postman API key" in result.stderr

    def test_a_mangled_paste_is_caught_locally(self, run: Run) -> None:
        result = run("import", "postman", env={"ELVA_POSTMAN_API_KEY": "PMAK-ab cd"})
        assert result.returncode == ExitCode.USAGE
        assert "whitespace" in result.stderr


class TestKeyStdin:
    def test_a_key_can_be_piped_in(self, run: Run) -> None:
        """It gets as far as needing Elva credentials, which is proof the key
        itself was accepted."""
        result = run("import", "postman", "--key-stdin", stdin_text=f"{KEY}\n")
        assert result.returncode == ExitCode.AUTH
        assert "not logged in" in result.stderr

    def test_nothing_piped_in_is_usage(self, run: Run) -> None:
        result = run("import", "postman", "--key-stdin")
        assert result.returncode == ExitCode.USAGE
        assert (
            "no Postman API key" in result.stderr
            or "--key-stdin has nothing piped into it" in result.stderr
        )


class TestUsageFailures:
    def test_list_with_a_collection_is_usage(self, run: Run) -> None:
        result = run("import", "postman", "Billing", "--list", env=SIGNED_OUT)
        assert result.returncode == ExitCode.USAGE
        assert "--list does not take" in result.stderr

    def test_a_plaintext_base_url_is_refused_before_the_key_moves(self, run: Run) -> None:
        result = run(
            "--base-url", "http://api.example.com", "import", "postman", "--list", env=SIGNED_OUT
        )
        assert result.returncode == ExitCode.USAGE
        assert "refusing to send" in result.stderr


class TestAuth:
    def test_a_valid_invocation_without_elva_credentials_is_auth(self, run: Run) -> None:
        """Every local check passed, so the only thing left to fail on is not
        being signed in to Elva."""
        result = run("import", "postman", "Billing", env=SIGNED_OUT)
        assert result.returncode == ExitCode.AUTH
        assert "not logged in" in result.stderr


class TestErrorsGoToStderr:
    def test_json_mode_keeps_stdout_clean_on_failure(self, run: Run) -> None:
        result = run("--json", "import", "postman")
        assert result.returncode == ExitCode.USAGE
        assert result.stdout == ""
        assert "ELVA_USAGE" in result.stderr

    def test_the_key_is_never_printed_back(self, run: Run) -> None:
        result = run("import", "postman", "Billing", env=SIGNED_OUT)
        assert KEY not in result.stdout
        assert KEY not in result.stderr


class TestItIsListedAsASubcommand:
    def test_bare_import_lists_postman(self, run: Run) -> None:
        result = run("import")
        assert result.returncode == ExitCode.USAGE
        assert "postman" in result.stdout

    def test_importing_a_postman_file_points_here(self, run: Run, workdir: Path) -> None:
        """`import spec` refuses a Postman collection; it should say where to
        take it instead."""
        (workdir / "collection.json").write_text('{"info":{"_postman_id":"abc"}}')
        result = run("import", "spec", "collection.json")
        assert result.returncode == ExitCode.USAGE
        assert "elva import postman" in result.stderr
