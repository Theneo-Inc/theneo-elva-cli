"""The single error boundary in main._run().

Every failure mode is exercised here rather than through subprocesses, so the
mapping from exception to exit code is asserted directly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Never

import pytest
import typer

from elva_cli import main
from elva_cli.errors import ApiError, AuthError, ElvaError, ExitCode, ValidationError

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


def _app_raising(exc: BaseException) -> Callable[..., Never]:
    def fake_app(*_args: object, **_kwargs: object) -> Never:
        raise exc

    return fake_app


def test_success_returns_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "app", lambda **_kwargs: None)
    assert main._run() == ExitCode.OK


def test_typer_exit_code_is_passed_through(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "app", _app_raising(typer.Exit(0)))
    assert main._run() == ExitCode.OK


def test_abort_maps_to_interrupted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "app", _app_raising(typer.Abort()))
    assert main._run() == ExitCode.INTERRUPTED


def test_keyboard_interrupt_maps_to_130(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "app", _app_raising(KeyboardInterrupt()))
    assert main._run() == ExitCode.INTERRUPTED


def test_framework_usage_error_maps_to_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    """Typer vendors Click, so its parsing errors are recognised by protocol."""
    monkeypatch.setattr(main, "app", _app_raising(typer.BadParameter("no such option")))
    assert main._run() == ExitCode.USAGE


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (AuthError("expired"), ExitCode.AUTH),
        (ValidationError("bad spec"), ExitCode.VALIDATION),
        (ApiError("502"), ExitCode.API),
        (ElvaError("generic"), ExitCode.UNEXPECTED),
    ],
)
def test_elva_errors_use_their_own_exit_code(
    monkeypatch: pytest.MonkeyPatch, error: ElvaError, expected: ExitCode
) -> None:
    monkeypatch.setattr(main, "app", _app_raising(error))
    assert main._run() == expected


def test_elva_error_prints_code_message_and_hint(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(main, "app", _app_raising(AuthError("session expired")))
    main._run()
    err = capsys.readouterr().err
    assert "ELVA_AUTH" in err
    assert "session expired" in err
    assert "elva auth login" in err


def test_unexpected_exception_writes_a_crash_file_and_no_traceback(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    monkeypatch.setattr("elva_cli.settings.paths.cache_dir", lambda: tmp_path, raising=True)
    monkeypatch.setattr(main, "app", _app_raising(RuntimeError("kaboom")))

    assert main._run() == ExitCode.UNEXPECTED

    err = capsys.readouterr().err
    assert "kaboom" in err
    assert "Traceback (most recent call last)" not in err

    crashes = list((tmp_path / "crashes").glob("crash-*.log"))
    assert len(crashes) == 1
    assert str(crashes[0]) in err

    contents = crashes[0].read_text(encoding="utf-8")
    assert "Traceback (most recent call last)" in contents
    assert "RuntimeError: kaboom" in contents


def test_crash_file_records_no_argv(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A crash report outlives the process; a secret on the command line must not."""
    monkeypatch.setattr("elva_cli.settings.paths.cache_dir", lambda: tmp_path, raising=True)
    monkeypatch.setattr("sys.argv", ["elva", "mcp", "create", "--secret", "hunter2"])
    monkeypatch.setattr(main, "app", _app_raising(RuntimeError("kaboom")))

    main._run()

    crash = next(iter((tmp_path / "crashes").glob("crash-*.log")))
    contents = crash.read_text(encoding="utf-8")
    assert "hunter2" not in contents


def test_unwritable_crash_dir_still_reports_the_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def boom() -> Path:
        raise OSError("read-only filesystem")

    monkeypatch.setattr("elva_cli.settings.paths.cache_dir", boom, raising=True)
    monkeypatch.setattr(main, "app", _app_raising(RuntimeError("kaboom")))

    assert main._run() == ExitCode.UNEXPECTED
    assert "kaboom" in capsys.readouterr().err
