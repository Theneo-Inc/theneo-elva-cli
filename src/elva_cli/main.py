"""Typer root and the single error boundary.

Nothing here does work. It resolves global options into a Ctx, dispatches, and
turns whatever comes back into an exit code. Every user-visible failure path in
the CLI funnels through here.

Currently wired: --version and --help. Global flags, the Ctx and the error
boundary land next.
"""

from __future__ import annotations

import platform

import typer

app = typer.Typer(
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
    raise typer.Exit(0)


@app.callback()
def root(
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        callback=_version_callback,
        is_eager=True,
        help="Show the current build version.",
    ),
) -> None:
    pass


def main() -> None:
    app()


if __name__ == "__main__":
    main()
