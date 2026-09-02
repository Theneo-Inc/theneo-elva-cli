"""Typer root and the single error boundary."""

from __future__ import annotations

import os
import platform
import sys
from pathlib import Path
from typing import Protocol, TypeGuard

import typer

from elva_cli.context import Ctx, GlobalOptions
from elva_cli.errors import ElvaError, ExitCode
from elva_cli.registry import LazyGroup

app = typer.Typer(
    cls=LazyGroup,
    name="elva",
    help="Elva - CLI for Theneo Elva.",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
    context_settings={"help_option_names": ["-h", "--help"]},
)


def _version_callback(value: bool) -> None:
    if not value:
        return
    from elva_cli import __version__

    machine = f"{platform.system().lower()}-{platform.machine()}"
    typer.echo(f"elva {__version__} (python {platform.python_version()}, {machine})")
    raise typer.Exit(ExitCode.OK)


@app.callback()
def root(
    click_ctx: typer.Context,
    profile: str | None = typer.Option(
        None, "--profile", envvar="ELVA_PROFILE", help="Named profile from your user config."
    ),
    base_url: str | None = typer.Option(
        None, "--base-url", envvar="ELVA_BASE_URL", help="Override the Elva API base URL."
    ),
    workspace: str | None = typer.Option(
        None, "--workspace", "-w", envvar="ELVA_WORKSPACE", help="Workspace to act on."
    ),
    collection: str | None = typer.Option(
        None, "--collection", "-c", envvar="ELVA_COLLECTION", help="Collection to act on."
    ),
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        callback=_version_callback,
        is_eager=True,
        help="Show the current build version.",
    ),
) -> None:
    click_ctx.obj = Ctx(
        GlobalOptions(
            profile=profile,
            base_url=base_url,
            workspace=workspace,
            collection=collection,
        ),
        cwd=Path.cwd(),
        env=os.environ,
    )


def report(error: ElvaError) -> None:
    """Render a user-facing error to stderr as code, message, then next action."""
    typer.secho(f"{error.code}: {error.message}", err=True, fg=typer.colors.RED)
    if error.hint:
        typer.secho(f"  -> {error.hint}", err=True, dim=True)


def write_crash(exc: BaseException) -> Path | None:
    """Persist a traceback for an unexpected failure and return its path.

    Deliberately records no argv: a crash report is written to disk and kept, and
    a mistyped secret on a command line must not outlive the process.
    """
    import time
    import traceback

    from elva_cli import __version__
    from elva_cli.settings.paths import crash_dir

    try:
        directory = crash_dir()
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"crash-{int(time.time())}-{os.getpid()}.log"
        target.write_text(
            f"elva {__version__}\n"
            f"python {platform.python_version()} on {platform.platform()}\n\n"
            + "".join(traceback.format_exception(exc)),
            encoding="utf-8",
        )
    except OSError:
        return None
    return target


class _FrameworkError(Protocol):
    """The shape every vendored Click exception exposes."""

    exit_code: int

    def show(self) -> None: ...


def _is_framework_error(exc: BaseException) -> TypeGuard[_FrameworkError]:
    """Recognise a Typer/Click argument-parsing failure."""
    return (
        type(exc).__module__.startswith("typer")
        and callable(getattr(exc, "show", None))
        and isinstance(getattr(exc, "exit_code", None), int)
    )


def _run() -> int:
    try:
        app(standalone_mode=False)
    except typer.Exit as exc:
        return int(exc.exit_code)
    except typer.Abort:
        return int(ExitCode.INTERRUPTED)
    except ElvaError as exc:
        report(exc)
        return int(exc.exit_code)
    except KeyboardInterrupt:
        typer.secho("interrupted", err=True, dim=True)
        return int(ExitCode.INTERRUPTED)
    except Exception as exc:
        if _is_framework_error(exc):
            exc.show()
            return int(exc.exit_code)
        path = write_crash(exc)
        report(
            ElvaError(
                f"unexpected error: {type(exc).__name__}: {exc}",
                code="ELVA_CRASH",
                hint=(
                    f"Details written to {path}. Please include that file when reporting this."
                    if path
                    else "Please report this, including the command you ran."
                ),
            )
        )
        return int(ExitCode.UNEXPECTED)
    return int(ExitCode.OK)


def main() -> None:
    sys.exit(_run())


if __name__ == "__main__":
    main()
