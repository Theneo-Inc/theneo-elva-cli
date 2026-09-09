"""Drives the real entry point, so the wiring is covered as well as the flow.

Nothing here reaches the network: every case is one the CLI refuses locally,
or --dry-run, which never sends anything at all.

Note the argument order. --collection and --workspace are global options on
the root callback, so they go *before* the subcommand -- `elva -c api import
spec file --update`, not `elva import spec file -c api`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from elva_cli.errors import ExitCode

if TYPE_CHECKING:
    import subprocess
    from collections.abc import Callable
    from pathlib import Path

    Run = Callable[..., subprocess.CompletedProcess[str]]

OPENAPI = 'openapi: 3.0.3\ninfo:\n  title: Payments\n  version: "2.1"\npaths:\n  /a:\n    get: {}\n'


def write_spec(workdir: Path, name: str = "payments.yaml", body: str = OPENAPI) -> Path:
    path = workdir / name
    path.write_text(body, encoding="utf-8")
    return path


class TestUsageFailures:
    def test_bare_import_lists_its_subcommands(self, run: Run) -> None:
        result = run("import")
        assert result.returncode == ExitCode.USAGE
        assert "spec" in result.stdout

    def test_no_source_at_all_is_usage(self, run: Run) -> None:
        result = run("import", "spec")
        assert result.returncode == ExitCode.USAGE
        assert "exactly one" in result.stderr

    def test_a_missing_file_is_usage(self, run: Run) -> None:
        result = run("import", "spec", "nope.yaml")
        assert result.returncode == ExitCode.USAGE
        assert "no such file" in result.stderr

    def test_an_unsupported_extension_names_what_is_allowed(self, run: Run, workdir: Path) -> None:
        write_spec(workdir, "notes.txt")
        result = run("import", "spec", "notes.txt")
        assert result.returncode == ExitCode.USAGE
        assert ".json" in result.stderr

    def test_an_unknown_format_is_usage(self, run: Run, workdir: Path) -> None:
        write_spec(workdir)
        result = run("import", "spec", "payments.yaml", "--format", "raml")
        assert result.returncode == ExitCode.USAGE
        assert "openapi" in result.stderr

    def test_a_postman_collection_is_refused(self, run: Run, workdir: Path) -> None:
        write_spec(workdir, "collection.json", '{"info":{"_postman_id":"abc"}}')
        result = run("import", "spec", "collection.json")
        assert result.returncode == ExitCode.USAGE
        assert "Postman" in result.stderr

    def test_update_without_a_collection_is_usage(self, run: Run, workdir: Path) -> None:
        write_spec(workdir)
        result = run("import", "spec", "payments.yaml", "--update")
        assert result.returncode == ExitCode.USAGE
        assert "which collection" in result.stderr

    def test_a_file_and_a_url_together_is_usage(self, run: Run, workdir: Path) -> None:
        write_spec(workdir)
        result = run("import", "spec", "payments.yaml", "--url", "https://x.dev/o.yaml")
        assert result.returncode == ExitCode.USAGE


class TestDryRun:
    """Reports without sending, so it works signed out."""

    def test_it_reports_what_would_be_created(self, run: Run, workdir: Path) -> None:
        write_spec(workdir)
        result = run("import", "spec", "payments.yaml", "--dry-run")
        assert result.returncode == ExitCode.OK
        assert "Would create 'Payments'" in result.stdout
        assert "Nothing was sent" in result.stdout

    def test_it_names_the_collection_it_would_update(self, run: Run, workdir: Path) -> None:
        write_spec(workdir)
        result = run(
            "-c", "payments-api", "import", "spec", "payments.yaml", "--update", "--dry-run"
        )
        assert result.returncode == ExitCode.OK
        assert "Would update 'payments-api'" in result.stdout

    def test_the_name_flag_overrides_the_spec_title(self, run: Run, workdir: Path) -> None:
        write_spec(workdir)
        result = run("import", "spec", "payments.yaml", "--name", "Chosen", "--dry-run")
        assert result.returncode == ExitCode.OK
        assert "Would create 'Chosen'" in result.stdout

    def test_json_mode_is_machine_readable(self, run: Run, workdir: Path) -> None:
        import json

        write_spec(workdir)
        result = run("--json", "import", "spec", "payments.yaml", "--dry-run")
        assert result.returncode == ExitCode.OK
        payload = json.loads(result.stdout)
        assert payload["action"] == "create"
        assert payload["collection"] == "Payments"
        assert payload["endpoints"] == 1

    def test_it_still_refuses_a_bad_invocation(self, run: Run, workdir: Path) -> None:
        write_spec(workdir, "notes.txt")
        result = run("import", "spec", "notes.txt", "--dry-run")
        assert result.returncode == ExitCode.USAGE


class TestStdin:
    def test_a_spec_can_be_piped_in(self, run: Run, workdir: Path) -> None:
        result = run("import", "spec", "-", "--dry-run", stdin_text=OPENAPI)
        assert result.returncode == ExitCode.OK
        assert "<stdin>" in result.stdout

    def test_empty_stdin_is_usage(self, run: Run) -> None:
        result = run("import", "spec", "-", "--dry-run", stdin_text="")
        assert result.returncode == ExitCode.USAGE


class TestAuth:
    def test_a_valid_invocation_without_credentials_is_auth(self, run: Run, workdir: Path) -> None:
        """Every local check passed, so the only thing left to fail on is
        not being signed in."""
        write_spec(workdir)
        result = run("import", "spec", "payments.yaml")
        assert result.returncode == ExitCode.AUTH
        assert "not logged in" in result.stderr


class TestErrorsGoToStderr:
    def test_json_mode_keeps_stdout_clean_on_failure(self, run: Run) -> None:
        result = run("--json", "import", "spec", "nope.yaml")
        assert result.returncode == ExitCode.USAGE
        assert result.stdout == ""
        assert "ELVA_USAGE" in result.stderr
