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
    invoke_without_command=True,
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
    prompt: str | None = typer.Option(
        None,
        "--prompt",
        help="Describe an MCP to build directly from this checkout, with an API contract.",
    ),
    path: Path | None = typer.Option(
        None, "--path", help="API source directory for --prompt; defaults to the checkout root."
    ),
    audience: str | None = typer.Option(
        None, "--audience", help="MCP audience: partner, public or internal. Asked when needed."
    ),
    api_base_url: str | None = typer.Option(
        None,
        "--api-base-url",
        help="Live upstream API URL, if it cannot be discovered from source.",
    ),
    auth_type: str | None = typer.Option(
        None, "--auth-type", help="Upstream authentication: bearer (default), api_key or none."
    ),
    api_key_header: str | None = typer.Option(
        None, "--api-key-header", help="Header used for upstream API-key authentication."
    ),
    resume: str | None = typer.Option(
        None, "--resume", help="Resume a local source planning job without uploading again."
    ),
    plan_only: bool = typer.Option(
        False, "--plan-only", help="Generate and save the review without creating the contract/MCP."
    ),
    out: Path | None = typer.Option(
        None, "--out", help="Save the prompt workflow's plan to this new file."
    ),
    name: str | None = typer.Option(
        None, "--name", help="Contract and MCP name for the prompt workflow."
    ),
    profile: str | None = typer.Option(
        None, "--profile", envvar="ELVA_PROFILE", help="Named set of defaults from your config."
    ),
    # Internal escape hatch for Theneo development and CI against staging. Users
    # only ever have prod, so it stays out of --help and out of the README.
    base_url: str | None = typer.Option(None, "--base-url", envvar="ELVA_BASE_URL", hidden=True),
    workspace: str | None = typer.Option(
        None, "--workspace", "-w", envvar="ELVA_WORKSPACE", help="Workspace to act on."
    ),
    collection: str | None = typer.Option(
        None, "--collection", "-c", envvar="ELVA_COLLECTION", help="Collection to act on."
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Emit machine readable JSON instead of formatted output."
    ),
    quiet: bool = typer.Option(
        False, "--quiet", "-q", help="Suppress hints and warnings. Data and errors still print."
    ),
    assume_yes: bool = typer.Option(
        False, "--yes", "-y", help="Answer every confirmation with yes. Required in CI."
    ),
    color: bool | None = typer.Option(
        None, "--color/--no-color", help="Force or disable colour. Honours NO_COLOR."
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
    ctx = Ctx(
        GlobalOptions(
            profile=profile,
            base_url=base_url,
            workspace=workspace,
            collection=collection,
            json_output=json_output,
            quiet=quiet,
            color=color,
            assume_yes=assume_yes,
        ),
        cwd=Path.cwd(),
        env=os.environ,
    )
    click_ctx.obj = ctx
    from elva_cli.core.api.timeout import use_timeout

    click_ctx.with_resource(use_timeout(lambda: ctx.settings.timeout))
    if prompt is not None or resume is not None:
        from elva_cli.commands.prompt import run_prompt
        from elva_cli.errors import UsageError

        if click_ctx.invoked_subcommand or (prompt is not None and resume is not None):
            raise UsageError("Use --prompt or --resume on its own, without a subcommand.")
        if resume and any(v is not None for v in (path, audience, name, auth_type, api_key_header)):
            raise UsageError(
                "--resume keeps the source, audience, name and authentication of the original job."
            )
        run_prompt(
            ctx,
            prompt=prompt,
            path=path,
            audience=audience,
            api_base_url=api_base_url,
            resume=resume,
            plan_only=plan_only,
            out=out,
            name=name,
            auth_type=auth_type,
            api_key_header=api_key_header,
        )
    elif (
        any(
            value is not None
            for value in (path, audience, api_base_url, out, name, auth_type, api_key_header)
        )
        or plan_only
    ):
        from elva_cli.errors import UsageError

        raise UsageError(
            "Prompt workflow options require --prompt or --resume. "
            "Put subcommand options after the subcommand."
        )
    elif click_ctx.invoked_subcommand is None:
        from elva_cli.errors import UsageError

        raise UsageError("Choose a command or describe your MCP with --prompt.")


def report(error: ElvaError) -> None:
    """Render a user-facing error to stderr.

    Goes through ui/ so errors look the same wherever they come from, but does not
    need a Ctx: the boundary has to work when building the Ctx is what failed.
    """
    from elva_cli.ui.output import report_error

    report_error(error, color=False if os.environ.get("NO_COLOR") else None)


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
        result = app(prog_name="elva", standalone_mode=False)
        return int(result) if isinstance(result, int) else int(ExitCode.OK)
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


def main() -> None:
    sys.exit(_run())


if __name__ == "__main__":
    main()
